"""
Phase 11.4 - Entry Point Detection.

Deterministic, static-analysis-only detection of likely Python execution
entry points.

No project code is imported or executed. Every signal is derived from
Python's built-in `ast` module plus filesystem and local dependency
structure, so the result is reproducible for a given source tree.
"""

import ast
import os

from core.intent_registry import register_tool


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules"}

# Filename conventions that commonly indicate a launcher.
# Supporting evidence only, never proof on its own.
CONVENTIONAL_NAMES = {"main.py", "app.py", "run.py", "cli.py", "__main__.py"}

# Curated, explicit sets for CLI/application construction detection.
# Deliberately narrow: matching broad names such as "run" would flag
# every module that calls subprocess.run, which is not evidence at all.
APP_CONSTRUCTORS = {"Typer", "Flask", "FastAPI", "OptionParser"}
APP_LAUNCH_CALLS = {
    ("typer", "run"),
    ("uvicorn", "run"),
    ("unittest", "main"),
    ("pytest", "main"),
}
APP_LAUNCH_ATTRS = {"mainloop"}
CLI_DECORATORS = {("click", "command"), ("click", "group"), ("typer", "command")}

# Deterministic additive scoring weights.
SCORE_MAIN_GUARD = 5
SCORE_ENTRY_FUNCTION_CALL = 2
SCORE_APP_CONSTRUCTION = 2
SCORE_ARGPARSE = 1
SCORE_SYS_ARGV = 1
SCORE_CONVENTIONAL_NAME = 1
SCORE_UNIMPORTED = 1

# Classification thresholds (see _classify for the full rule set).
THRESHOLD_LIKELY = 3
THRESHOLD_POSSIBLE = 2


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


def _is_name_dunder(node):
    return isinstance(node, ast.Name) and node.id == "__name__"


def _is_main_string(node):
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == "__main__"
    )


def _is_main_guard(node):
    """True when node is `if __name__ == "__main__":` in either operand order."""
    if not isinstance(node, ast.If):
        return False

    test = node.test
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False

    left = test.left
    right = test.comparators[0]
    if _is_name_dunder(left) and _is_main_string(right):
        return True
    return _is_main_string(left) and _is_name_dunder(right)


def _find_main_guards(tree):
    return [node for node in ast.walk(tree) if _is_main_guard(node)]


def _module_level_functions(tree):
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _functions_called_from_guards(guards, module_functions):
    """Locally defined module-level functions invoked inside a __main__ block."""
    called = set()
    for guard in guards:
        for statement in guard.body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in module_functions:
                        called.add(node.func.id)
    return sorted(called)


def _import_aliases(tree):
    """
    Local binding names for `sys` and for `sys.argv`, honouring aliases so
    `import sys as system` / `from sys import argv as a` are still detected.
    """
    sys_aliases = set()
    argv_aliases = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sys":
                    sys_aliases.add(alias.asname or "sys")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "sys" and not node.level:
                for alias in node.names:
                    if alias.name == "argv":
                        argv_aliases.add(alias.asname or "argv")

    return sys_aliases, argv_aliases


def _uses_argparse(tree):
    """An ArgumentParser is constructed somewhere in the module."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "ArgumentParser":
            return True
        if isinstance(func, ast.Name) and func.id == "ArgumentParser":
            return True
    return False


def _uses_sys_argv(tree, sys_aliases, argv_aliases):
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "argv":
            if isinstance(node.value, ast.Name) and node.value.id in sys_aliases:
                return True
        elif isinstance(node, ast.Name) and node.id in argv_aliases:
            return True
    return False


def _constructs_application(tree):
    """
    Curated detection of CLI/application construction or launch.
    Matches only the explicit names in APP_CONSTRUCTORS, APP_LAUNCH_CALLS,
    APP_LAUNCH_ATTRS and CLI_DECORATORS - no semantic guessing.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr in APP_CONSTRUCTORS or func.attr in APP_LAUNCH_ATTRS:
                    return True
                if isinstance(func.value, ast.Name):
                    if (func.value.id, func.attr) in APP_LAUNCH_CALLS:
                        return True
            elif isinstance(func, ast.Name) and func.id in APP_CONSTRUCTORS:
                return True

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    if (target.value.id, target.attr) in CLI_DECORATORS:
                        return True

    return False


def _classify(has_main_guard, score):
    """
    Deterministic classification (first matching rule wins):

    1. "Strong Entry Point"
       - the module contains an `if __name__ == "__main__"` block.
         This alone guarantees score >= SCORE_MAIN_GUARD (5) and is the
         only signal that is definitional rather than circumstantial:
         the file is executable by language semantics.
    2. "Likely Entry Point"
       - no __main__ block, but score >= THRESHOLD_LIKELY (3), i.e. at
         least two corroborating signals beyond a single weak hint.
    3. "Possible Entry Point"
       - no __main__ block, but score >= THRESHOLD_POSSIBLE (2), i.e. two
         weak signals or one moderate signal.
    4. None (not an entry-point candidate)
       - score <= 1. A single weak signal such as "nobody imports this"
         or "the filename looks like a launcher" is never sufficient.

    Because SCORE_UNIMPORTED is 1 and below THRESHOLD_POSSIBLE, an
    unimported module can never be promoted to a candidate by that fact
    alone; it is reported separately as a root module instead.
    """
    if has_main_guard:
        return "Strong Entry Point"
    if score >= THRESHOLD_LIKELY:
        return "Likely Entry Point"
    if score >= THRESHOLD_POSSIBLE:
        return "Possible Entry Point"
    return None


def _analyze_file(filepath, tree, is_init, is_unimported):
    """Score one parsed module and collect human-readable evidence."""
    basename = os.path.basename(_posix_rel(filepath))
    score = 0
    evidence = []

    guards = _find_main_guards(tree)
    has_main_guard = bool(guards)
    if has_main_guard:
        score += SCORE_MAIN_GUARD
        evidence.append(f'__name__ == "__main__" block (+{SCORE_MAIN_GUARD})')

        called = _functions_called_from_guards(guards, _module_level_functions(tree))
        if called:
            score += SCORE_ENTRY_FUNCTION_CALL
            names = ", ".join(f"{name}()" for name in called)
            evidence.append(
                f"{names} called from __main__ block (+{SCORE_ENTRY_FUNCTION_CALL})"
            )

    if _constructs_application(tree):
        score += SCORE_APP_CONSTRUCTION
        evidence.append(
            f"constructs or launches a CLI/application (+{SCORE_APP_CONSTRUCTION})"
        )

    if _uses_argparse(tree):
        score += SCORE_ARGPARSE
        evidence.append(f"argparse.ArgumentParser usage (+{SCORE_ARGPARSE})")

    sys_aliases, argv_aliases = _import_aliases(tree)
    if _uses_sys_argv(tree, sys_aliases, argv_aliases):
        score += SCORE_SYS_ARGV
        evidence.append(f"sys.argv usage (+{SCORE_SYS_ARGV})")

    # Package markers never earn filename-convention or root credit, so an
    # __init__.py is never promoted merely for being unimported.
    if not is_init:
        if basename in CONVENTIONAL_NAMES:
            score += SCORE_CONVENTIONAL_NAME
            evidence.append(
                f"conventional launcher filename ({basename}) (+{SCORE_CONVENTIONAL_NAME})"
            )
        if is_unimported:
            score += SCORE_UNIMPORTED
            evidence.append(
                f"not imported by any local module (+{SCORE_UNIMPORTED})"
            )

    return {
        "score": score,
        "evidence": evidence,
        "has_main_guard": has_main_guard,
        "classification": _classify(has_main_guard, score),
    }


def _build_import_counts(python_files):
    """
    Local dependency evidence: how many other project modules import each
    file. Reuses the same resolution approach as the existing project
    graph so root detection stays consistent across tools.
    """
    module_index = _build_module_index(python_files)
    trees = {}
    unparseable = []
    imported_by = {_posix_rel(path): 0 for path in python_files}

    for filepath in python_files:
        source_rel = _posix_rel(filepath)
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
            tree = ast.parse(source)
        except (SyntaxError, ValueError, OSError, RecursionError):
            unparseable.append(source_rel)
            continue
        trees[source_rel] = tree

    for source_rel, tree in trees.items():
        filepath = os.path.join(PROJECT_ROOT, source_rel.replace("/", os.sep))
        for name in _imported_modules(filepath, tree):
            target = _resolve_local(name, module_index)
            if target and target != source_rel:
                imported_by[target] = imported_by.get(target, 0) + 1

    return trees, imported_by, sorted(unparseable)


def _format_candidates(records):
    if not records:
        return ["- (none)"]

    lines = []
    for rec in records:
        lines.append(f"- {rec['path']}")
        lines.append(f"    Score: {rec['score']}")
        lines.append("    Evidence:")
        for item in rec["evidence"]:
            lines.append(f"    - {item}")
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _format_list(items):
    if not items:
        return ["- (none)"]
    return [f"- {item}" for item in items]


def detect_entry_points(args):
    python_files = list(_iter_python_files())
    if not python_files:
        return "No Python files found in project"

    trees, imported_by, unparseable = _build_import_counts(python_files)

    strong = []
    likely = []
    possible = []
    root_modules = []
    ignored_inits = []

    for filepath in sorted(python_files, key=_posix_rel):
        source_rel = _posix_rel(filepath)
        is_init = os.path.basename(source_rel) == "__init__.py"
        if is_init:
            ignored_inits.append(source_rel)

        tree = trees.get(source_rel)
        if tree is None:
            continue

        is_unimported = imported_by.get(source_rel, 0) == 0
        result = _analyze_file(filepath, tree, is_init, is_unimported)
        record = {
            "path": source_rel,
            "score": result["score"],
            "evidence": result["evidence"],
        }

        classification = result["classification"]
        if classification == "Strong Entry Point":
            strong.append(record)
        elif classification == "Likely Entry Point":
            likely.append(record)
        elif classification == "Possible Entry Point":
            possible.append(record)
        elif is_unimported and not is_init:
            # Unimported but without executable evidence: a root of the
            # dependency graph, not an application entry point.
            root_modules.append(source_rel)

    lines = ["Entry Point Detection", "", "Strong Entry Points:", ""]
    if strong:
        lines.extend(_format_candidates(strong))
    else:
        lines.append("No strong Python entry point detected.")

    lines.extend(["", "Likely Entry Points:", ""])
    lines.extend(_format_candidates(likely))

    lines.extend(["", "Possible Entry Points:", ""])
    lines.extend(_format_candidates(possible))

    lines.extend(["", "Root Modules Without Strong Entry-Point Evidence:", ""])
    lines.extend(_format_list(root_modules))

    lines.extend(["", "Ignored:", ""])
    if ignored_inits:
        lines.extend(f"- {path}" for path in ignored_inits)
        lines.append("  (package markers: excluded from filename and root evidence)")
    else:
        lines.append("- (none)")

    if unparseable:
        lines.extend(["", "Unparseable Files (skipped):", ""])
        lines.extend(f"- {path}" for path in unparseable)

    lines.extend(
        [
            "",
            "Summary:",
            f"Python Files: {len(python_files)}",
            f"Strong Entry Points: {len(strong)}",
            f"Likely Entry Points: {len(likely)}",
            f"Possible Entry Points: {len(possible)}",
            f"Root Modules Without Strong Evidence: {len(root_modules)}",
        ]
    )
    return "\n".join(lines)


register_tool(
    name="detect_entry_points",
    description="Detect likely Python execution entry points in the current project",
    parameters={},
    handler=detect_entry_points,
    risk_level="safe",
)
