"""
Phase 11.6 - Dead Code Detection.

Deterministic, static-analysis-only identification of unused-code
CANDIDATES at three levels: modules, functions/methods, and classes.

Deadness cannot be proven statically in Python. Dynamic imports,
reflection, plugin registration, decorators, getattr dispatch, external
callers and runtime configuration can all keep apparently unreferenced
code alive. Nothing here claims a definition is dead; it reports
candidates together with the evidence and a transparent confidence level.

No project code is imported or executed, no source file is modified, and
the LLM is not consulted.

Entry-point facts are reused from modules.dev.entry_point_detector rather
than reimplemented, so the two tools cannot disagree about what counts as
an entry point. Import resolution follows the conventions established by
project_graph.py so "local module" means the same thing across Phase 11.
"""

import ast
import os

from core.intent_registry import register_tool
import modules.dev.entry_point_detector as entry_point_detector


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules"}

# Decorators that mark a definition as an abstract/interface declaration.
# Implementations are reached through the base class, so the declaration
# itself is never reported.
ABSTRACT_DECORATORS = {
    "abstractmethod",
    "abstractproperty",
    "abstractclassmethod",
    "abstractstaticmethod",
}

# Decorators that do not imply dynamic registration: they change how an
# attribute is accessed, not whether it is discoverable, so they must not
# soften confidence on their own.
NEUTRAL_DECORATORS = {"staticmethod", "classmethod", "property", "override"}


def _posix_rel(filepath):
    return os.path.relpath(filepath, PROJECT_ROOT).replace("\\", "/")


def _path_to_module(filepath):
    rel = _posix_rel(filepath)
    if rel.endswith(".py"):
        rel = rel[:-3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return rel.replace("/", ".")


def _iter_python_files():
    for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def _build_module_index(python_files):
    index = {}
    for filepath in python_files:
        module = _path_to_module(filepath)
        index[module] = _posix_rel(filepath)
        rel = _posix_rel(filepath)
        if rel.endswith("/__init__.py"):
            package = rel[: -len("/__init__.py")].replace("/", ".")
            index.setdefault(package, rel)
    return index


def _resolve_relative(filepath, level, module):
    rel_dir = os.path.dirname(_posix_rel(filepath))
    parts = [] if rel_dir in ("", ".") else rel_dir.split("/")
    up = level - 1
    if up > len(parts):
        return None
    parent = parts[: len(parts) - up]
    if module:
        parent.extend(module.split("."))
    if not parent:
        return None
    return ".".join(parent)


def _imported_modules(filepath, tree):
    names = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                base = _resolve_relative(filepath, node.level, node.module)
            else:
                base = node.module

            if base:
                names.append(base)
                for alias in node.names:
                    if alias.name and alias.name != "*":
                        names.append(f"{base}.{alias.name}")
            elif node.level:
                for alias in node.names:
                    if alias.name and alias.name != "*":
                        resolved = _resolve_relative(filepath, node.level, alias.name)
                        if resolved:
                            names.append(resolved)

    return names


def _resolve_local(module_name, module_index):
    if module_name in module_index:
        return module_index[module_name]
    parts = module_name.split(".")
    while len(parts) > 1:
        parts.pop()
        candidate = ".".join(parts)
        if candidate in module_index:
            return module_index[candidate]
    return None


def _parse_project():
    """
    Parse every project Python file once.

    Returns (files, trees, graph, unparseable). `graph` maps a module to
    the sorted local modules it imports; self-edges and unresolvable or
    non-local imports are dropped. Files that fail to parse are recorded
    and skipped without aborting the run.
    """
    python_files = list(_iter_python_files())
    module_index = _build_module_index(python_files)
    files = sorted(_posix_rel(path) for path in python_files)
    trees = {}
    unparseable = []

    for filepath in python_files:
        source_rel = _posix_rel(filepath)
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
            trees[source_rel] = ast.parse(source)
        except (SyntaxError, OSError, ValueError, RecursionError):
            unparseable.append(source_rel)

    graph = {}
    for source_rel, tree in trees.items():
        filepath = os.path.join(PROJECT_ROOT, source_rel.replace("/", os.sep))
        targets = set()
        for name in _imported_modules(filepath, tree):
            target = _resolve_local(name, module_index)
            if target and target != source_rel:
                targets.add(target)
        graph[source_rel] = sorted(targets)

    return files, trees, graph, sorted(unparseable)


def _entry_point_facts(files, trees, graph):
    """
    Reuse the Phase 11.4 detector for entry-point facts.

    entry_point_detector._analyze_file resolves paths against that
    module's own PROJECT_ROOT, so it is synced to ours for the duration of
    the call and restored afterwards. In normal operation both modules
    compute the same root and the sync is a no-op; it only matters when a
    caller has retargeted this module at another tree.

    Returns (entry_points, guard_called) where entry_points maps a module
    to its entry-point classification and guard_called maps a module to
    the set of functions invoked from its __main__ block.
    """
    imported_by = {path: 0 for path in files}
    for source in files:
        for target in graph.get(source, []):
            imported_by[target] = imported_by.get(target, 0) + 1

    entry_points = {}
    guard_called = {}

    saved_root = entry_point_detector.PROJECT_ROOT
    entry_point_detector.PROJECT_ROOT = PROJECT_ROOT
    try:
        for module, tree in trees.items():
            filepath = os.path.join(PROJECT_ROOT, module.replace("/", os.sep))
            is_init = os.path.basename(module) == "__init__.py"
            result = entry_point_detector._analyze_file(
                filepath, tree, is_init, imported_by.get(module, 0) == 0
            )
            if result["classification"]:
                entry_points[module] = result["classification"]

            guards = entry_point_detector._find_main_guards(tree)
            if guards:
                guard_called[module] = set(
                    entry_point_detector._functions_called_from_guards(
                        guards, entry_point_detector._module_level_functions(tree)
                    )
                )
    finally:
        entry_point_detector.PROJECT_ROOT = saved_root

    return entry_points, guard_called


def _reachable_modules(graph, entry_points):
    """Modules reachable from any detected entry point (breadth-first)."""
    reachable = set()
    queue = sorted(entry_points)
    reachable.update(queue)
    while queue:
        module = queue.pop()
        for target in graph.get(module, []):
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
    return reachable


def _decorator_names(node):
    names = []
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


def _base_names(node):
    names = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _is_dunder(name):
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def _collect_definitions(module, tree):
    """
    Collect top-level functions, top-level classes, and their methods.

    Local variables and nested/inner functions are out of scope for this
    phase. Each definition carries an owner path used later to separate a
    definition's own internal references from external ones.
    """
    definitions = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.append(
                {
                    "kind": "function",
                    "module": module,
                    "name": node.name,
                    "qualname": node.name,
                    "owner": (node.name,),
                    "lineno": node.lineno,
                    "decorators": _decorator_names(node),
                    "class_name": None,
                    "bases": [],
                }
            )
        elif isinstance(node, ast.ClassDef):
            bases = _base_names(node)
            definitions.append(
                {
                    "kind": "class",
                    "module": module,
                    "name": node.name,
                    "qualname": node.name,
                    "owner": (node.name,),
                    "lineno": node.lineno,
                    "decorators": _decorator_names(node),
                    "class_name": None,
                    "bases": bases,
                }
            )
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    definitions.append(
                        {
                            "kind": "method",
                            "module": module,
                            "name": member.name,
                            "qualname": f"{node.name}.{member.name}",
                            "owner": (node.name, member.name),
                            "lineno": member.lineno,
                            "decorators": _decorator_names(member),
                            "class_name": node.name,
                            "bases": bases,
                        }
                    )

    return definitions


def _collect_references(tree):
    """
    Collect identifier references tagged with the definition that encloses
    them, so a definition's own body can be excluded later.

    Three reference kinds are distinguished, all from AST nodes rather
    than text search:

      "name"      - ast.Name in Load context (bare use, e.g. helper())
      "attribute" - ast.Attribute .attr (e.g. module.helper, obj.helper)
      "import"    - a name bound by `from module import name [as alias]`

    Store targets, comments and string contents are never counted. A
    definition's own header (its name) is not an ast.Name node, so a
    definition can never reference itself into life.
    """
    references = []

    def visit(node, owner):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Decorators, bases and signatures evaluate in the enclosing
            # scope, so they belong to the current owner, not the new one.
            for decorator in node.decorator_list:
                visit(decorator, owner)
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    visit(base, owner)
                for keyword in node.keywords:
                    visit(keyword, owner)
            else:
                visit(node.args, owner)
                if node.returns is not None:
                    visit(node.returns, owner)
            inner = owner + (node.name,)
            for statement in node.body:
                visit(statement, inner)
            return

        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                references.append((owner, "name", node.id))
        elif isinstance(node, ast.Attribute):
            references.append((owner, "attribute", node.attr))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name and alias.name != "*":
                    references.append((owner, "import", alias.name))

        for child in ast.iter_child_nodes(node):
            visit(child, owner)

    for statement in tree.body:
        visit(statement, ())

    return references


def _build_reference_index(trees):
    """
    Index references for lookup.

    name_refs[name]      -> set of (module, owner)   bare-name uses
    attr_refs[name]      -> set of (module, owner)   attribute accesses
    import_refs[name]    -> set of (module, owner)   from-import bindings
    """
    name_refs = {}
    attr_refs = {}
    import_refs = {}

    buckets = {"name": name_refs, "attribute": attr_refs, "import": import_refs}

    for module, tree in trees.items():
        for owner, kind, name in _collect_references(tree):
            buckets[kind].setdefault(name, set()).add((module, owner))

    return name_refs, attr_refs, import_refs


def _is_internal(module, owner, definition):
    """True when a reference sits inside the definition's own body."""
    if module != definition["module"]:
        return False
    own = definition["owner"]
    return owner[: len(own)] == own


def _has_external_reference(definition, name_refs, attr_refs, import_refs, importers):
    """
    Decide whether a definition is referenced anywhere outside itself.

    Bare-name matches only count from the defining module or from modules
    that actually import it, which prevents an unrelated identifier of the
    same name in an unrelated module from resurrecting dead code.

    Attribute and from-import matches count from anywhere. Receiver types
    are not inferred, so `obj.helper` cannot be tied to a specific class;
    counting them broadly errs toward under-reporting candidates, which is
    the correct direction for a tool that must not claim false deadness.
    It also covers re-export chains, where the importing module never
    names the defining module directly.
    """
    name = definition["name"]
    module = definition["module"]
    allowed = importers.get(module, set()) | {module}

    for ref_module, owner in name_refs.get(name, ()):
        if ref_module in allowed and not _is_internal(ref_module, owner, definition):
            return True

    for ref_module, owner in attr_refs.get(name, ()):
        if not _is_internal(ref_module, owner, definition):
            return True

    for ref_module, owner in import_refs.get(name, ()):
        if not _is_internal(ref_module, owner, definition):
            return True

    return False


def _exemption(definition, entry_points, guard_called):
    """
    Reasons a definition is never reported, regardless of references.

    Returns the reason string, or None when the definition is analyzable.
    """
    name = definition["name"]
    module = definition["module"]

    if definition["kind"] == "method" and _is_dunder(name):
        return "dunder method (may be invoked implicitly by Python)"

    for decorator in definition["decorators"]:
        if decorator in ABSTRACT_DECORATORS:
            return "abstract/interface declaration"

    if name in guard_called.get(module, set()):
        return "invoked from this module's __main__ block"

    if name == "main" and module in entry_points:
        return "main() of a detected entry-point module"

    return None


def _confidence(definition, module_is_candidate):
    """
    Deterministic confidence for a definition with no detected references
    (first matching rule wins):

    1. "Medium Candidate"
       - the definition carries a non-neutral decorator. Decorators can
         register or expose an object dynamically, so an absent reference
         proves less.
       - or the definition is override-like: a method whose class derives
         from something other than object, or whose name is defined on
         another class in the project. Such methods are usually reached
         through a base-class call site that static analysis cannot see.
    2. "High Candidate"
       - no external references, no exemption, no decorator and no
         override-like evidence.

    Modules are scored separately in _module_candidates. A definition
    living inside a candidate module is not downgraded - the module being
    unused makes its contents more suspect, not less - but the fact is
    recorded as evidence.
    """
    evidence = ["No external references detected"]

    informative = [d for d in definition["decorators"] if d not in NEUTRAL_DECORATORS]
    override_like = definition.get("override_like", False)

    if informative:
        evidence.append(f"Decorated definition ({', '.join(sorted(informative))})")
    if override_like:
        evidence.append("Override-like method (may be called through a base class)")
    if module_is_candidate:
        evidence.append("Declared in a module that is itself a candidate")

    if informative or override_like:
        return "Medium Candidate", evidence
    return "High Candidate", evidence


def _module_candidates(files, graph, entry_points, reachable, has_entry_points, unparseable):
    """
    Deterministic module confidence (first matching rule wins):

    1. Never reported
       - __init__.py package markers, any module the Phase 11.4 detector
         classifies as an entry point, and any module that failed to
         parse. An unparseable file's contents were never analyzed, so
         characterising it as unused would overstate what is known; it is
         disclosed in the skipped section instead.
    2. "High Candidate"
       - no local module imports it and it is not an entry point.
    3. "Medium Candidate"
       - it is imported, but only from modules that are themselves
         unreachable from any detected entry point. Requires at least one
         entry point to exist, otherwise every module is trivially
         unreachable and the signal is meaningless.
    """
    imported_by = {path: [] for path in files}
    for source in files:
        for target in graph.get(source, []):
            imported_by.setdefault(target, []).append(source)

    skipped = set(unparseable)
    candidates = []
    for module in files:
        if os.path.basename(module) == "__init__.py":
            continue
        if module in entry_points:
            continue
        if module in skipped:
            continue

        importers = sorted(imported_by.get(module, []))
        if not importers:
            candidates.append(
                {
                    "module": module,
                    "confidence": "High Candidate",
                    "evidence": [
                        "No local import references detected",
                        "Not a detected entry point",
                        "Not an __init__.py package marker",
                    ],
                }
            )
        elif has_entry_points and module not in reachable:
            candidates.append(
                {
                    "module": module,
                    "confidence": "Medium Candidate",
                    "evidence": [
                        "Not reachable from any detected entry point",
                        f"Imported only by unreachable modules: {', '.join(importers)}",
                        "Not a detected entry point",
                    ],
                }
            )

    return candidates


def _format_candidate(label, confidence, evidence):
    lines = [f"- {label}", f"  Confidence: {confidence}", "  Evidence:"]
    lines.extend(f"  - {item}" for item in evidence)
    return lines


def detect_dead_code(args):
    files, trees, graph, unparseable = _parse_project()
    if not files:
        return "No Python files found in project"

    entry_points, guard_called = _entry_point_facts(files, trees, graph)
    reachable = _reachable_modules(graph, entry_points)
    has_entry_points = bool(entry_points)

    module_candidates = _module_candidates(
        files, graph, entry_points, reachable, has_entry_points, unparseable
    )
    candidate_modules = {item["module"] for item in module_candidates}

    definitions = []
    for module in sorted(trees):
        definitions.extend(_collect_definitions(module, trees[module]))

    # Method names defined on more than one class suggest an interface or
    # override family, which makes a missing reference weaker evidence.
    classes_by_method = {}
    for definition in definitions:
        if definition["kind"] == "method":
            classes_by_method.setdefault(definition["name"], set()).add(
                (definition["module"], definition["class_name"])
            )

    for definition in definitions:
        if definition["kind"] != "method":
            definition["override_like"] = False
            continue
        inherits = any(base != "object" for base in definition["bases"])
        shared = len(classes_by_method.get(definition["name"], ())) > 1
        definition["override_like"] = inherits or shared

    importers = {path: set() for path in files}
    for source in files:
        for target in graph.get(source, []):
            importers.setdefault(target, set()).add(source)

    name_refs, attr_refs, import_refs = _build_reference_index(trees)

    function_candidates = []
    class_candidates = []
    exempt_count = 0
    referenced_functions = 0
    referenced_classes = 0
    total_functions = 0
    total_classes = 0

    analyzed = []
    for definition in definitions:
        if definition["kind"] == "class":
            total_classes += 1
        else:
            total_functions += 1

        reason = _exemption(definition, entry_points, guard_called)
        if reason:
            exempt_count += 1
            continue

        if _has_external_reference(
            definition, name_refs, attr_refs, import_refs, importers
        ):
            if definition["kind"] == "class":
                referenced_classes += 1
            else:
                referenced_functions += 1
            continue

        analyzed.append(definition)

    unreferenced_classes = {
        (d["module"], d["name"]) for d in analyzed if d["kind"] == "class"
    }

    for definition in analyzed:
        # A method of a class that is itself a candidate adds no
        # information; it is summarised on the class instead.
        if definition["kind"] == "method":
            if (definition["module"], definition["class_name"]) in unreferenced_classes:
                continue

        confidence, evidence = _confidence(
            definition, definition["module"] in candidate_modules
        )
        record = {
            "label": f"{definition['module']}::{definition['qualname']}",
            "confidence": confidence,
            "evidence": evidence,
            "module": definition["module"],
            "qualname": definition["qualname"],
        }
        if definition["kind"] == "class":
            methods = sum(
                1
                for d in analyzed
                if d["kind"] == "method"
                and d["module"] == definition["module"]
                and d["class_name"] == definition["name"]
            )
            if methods:
                record["evidence"] = list(evidence) + [
                    f"{methods} method(s) in this class are also unreferenced"
                ]
            class_candidates.append(record)
        else:
            function_candidates.append(record)

    function_candidates.sort(key=lambda r: r["label"])
    class_candidates.sort(key=lambda r: r["label"])

    lines = ["Dead Code Analysis", "", "Potentially Unused Modules:", ""]
    if module_candidates:
        for item in module_candidates:
            lines.extend(
                _format_candidate(item["module"], item["confidence"], item["evidence"])
            )
            lines.append("")
    else:
        lines.extend(["- None", ""])

    lines.extend(["Potentially Unused Functions:", ""])
    if function_candidates:
        for item in function_candidates:
            lines.extend(
                _format_candidate(item["label"], item["confidence"], item["evidence"])
            )
            lines.append("")
    else:
        lines.extend(["- None", ""])

    lines.extend(["Potentially Unused Classes:", ""])
    if class_candidates:
        for item in class_candidates:
            lines.extend(
                _format_candidate(item["label"], item["confidence"], item["evidence"])
            )
            lines.append("")
    else:
        lines.extend(["- None", ""])

    live_modules = len(files) - len(module_candidates)
    lines.extend(
        [
            "Referenced / Active Code:",
            f"- Modules not reported as candidates: {live_modules} of {len(files)}",
            f"- Functions/methods with detected references: {referenced_functions} of {total_functions}",
            f"- Classes with detected references: {referenced_classes} of {total_classes}",
            f"- Definitions exempt from analysis: {exempt_count}",
            f"- Detected entry points: {len(entry_points)}",
            "",
        ]
    )

    if unparseable:
        lines.append("Unparseable Files (skipped):")
        lines.extend(f"- {path}" for path in unparseable)
        lines.append("")

    all_candidates = module_candidates + function_candidates + class_candidates
    high = sum(1 for c in all_candidates if c["confidence"] == "High Candidate")
    medium = sum(1 for c in all_candidates if c["confidence"] == "Medium Candidate")

    lines.extend(
        [
            "Summary:",
            "",
            f"Python Files: {len(files)}",
            "",
            "Modules:",
            f"- Total: {len(files)}",
            f"- Potentially Unused: {len(module_candidates)}",
            "",
            "Functions:",
            f"- Total: {total_functions}",
            f"- Potentially Unused: {len(function_candidates)}",
            "",
            "Classes:",
            f"- Total: {total_classes}",
            f"- Potentially Unused: {len(class_candidates)}",
            "",
            f"High-Confidence Candidates: {high}",
            f"Medium-Confidence Candidates: {medium}",
            "",
            "Important:",
            "These are static-analysis candidates, not proof of dead code.",
            "Dynamic imports, reflection, external callers, runtime registration,",
            "and other dynamic Python behavior may cause false positives.",
        ]
    )
    return "\n".join(lines)


register_tool(
    name="detect_dead_code",
    description="Detect potentially unused modules, functions and classes in the current project",
    parameters={},
    handler=detect_dead_code,
    risk_level="safe",
)
