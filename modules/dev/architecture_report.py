"""
Phase 11.7 - Architecture Report.

The synthesis layer of Project Intelligence. Every earlier Phase 11 tool
answers one question about a repository; this tool combines their answers
into a single architectural picture.

Design principle: deterministic facts and architectural interpretation are
kept strictly apart. Facts come from `ast`, the filesystem and the local
dependency graph. Interpretation is a set of documented rules applied to
those facts, and every observation, recommendation and score carries the
computed evidence that produced it. Nothing is inferred by an LLM and
nothing is asserted that cannot be traced back to a number in this file.

Reuse rather than reimplementation is deliberate. Graph construction,
entry-point scoring, cycle detection, dead-code classification and module
classification are imported from the tools that own them, so this report
cannot drift out of agreement with `detect_entry_points`,
`detect_circular_imports`, `detect_dead_code`, `show_project_graph` or
`analyze_module_relationships`. No existing tool is modified.

No project code is imported or executed and no source file is written.
"""

import ast
import os

from core.intent_registry import register_tool

import modules.dev.circular_import_detector as circular_import_detector
import modules.dev.dead_code_detector as dead_code_detector
import modules.dev.entry_point_detector as entry_point_detector
import modules.dev.module_relationship as module_relationship


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules"}

# Documentation and test discovery. Deliberately convention-based: these
# are ecosystem-wide Python conventions, not names taken from any one
# project.
README_STEMS = {"readme"}
DOC_DIRS = {"docs", "doc"}
TEST_DIRS = {"tests", "test"}

# Execution flow rendering.
FLOW_MAX_STEPS = 8
FLOW_COLLAPSE_FANOUT = 5
FLOW_MAX_ENTRY_POINTS = 3

# Observation thresholds.
CENTRAL_ROUTER_SHARE = 0.25
SHARED_SERVICE_DEPENDENTS = 3
SHARED_SERVICE_PACKAGES = 2
SHARED_SERVICE_REPORTED = 3
PLUGIN_PACKAGE_MODULES = 3
LOW_COUPLING_MEAN = 3.0
LAYERED_MIN_LAYERS = 3

# Health rubric constants (see _health_score for the full rubric).
PENALTY_NO_README = 2
PENALTY_NO_TESTS = 2
PENALTY_NO_PACKAGES = 2
PENALTY_UNPARSEABLE = 1
PENALTY_FIRST_CYCLE = 4
PENALTY_EXTRA_CYCLE = 1
PENALTY_CYCLE_CAP = 6
PENALTY_HEAVY_COUPLING = 2
HEAVY_COUPLING_MEAN = 5.0
PENALTY_DEAD_HIGH_CAP = 4
PENALTY_DEAD_MEDIUM_CAP = 2
PENALTY_ISOLATED_CAP = 3
ENTRY_SCORE_NONE = 2
ENTRY_SCORE_WEAK = 6
ENTRY_SCORE_STRONG = 10
ENTRY_MULTI_PENALTY_CAP = 3


# ---------------------------------------------------------------------------
# Deterministic fact gathering
# ---------------------------------------------------------------------------


def _package_of(module_path):
    """Package = the directory holding the module. Root files group as (root)."""
    directory = os.path.dirname(module_path)
    return directory if directory else "(root)"


def _dotted(package):
    return "(root)" if package == "(root)" else package.replace("/", ".")


def _has_documentation():
    """A README at the project root, or a docs/ directory anywhere."""
    try:
        entries = os.listdir(PROJECT_ROOT)
    except OSError:
        return False, []

    found = []
    for name in entries:
        stem = os.path.splitext(name)[0].lower()
        if stem in README_STEMS and os.path.isfile(os.path.join(PROJECT_ROOT, name)):
            found.append(name)

    for dirpath, dirnames, _ in os.walk(PROJECT_ROOT):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in dirnames:
            if name.lower() in DOC_DIRS:
                found.append(os.path.relpath(os.path.join(dirpath, name), PROJECT_ROOT))

    return bool(found), sorted(set(found))


def _has_tests(files):
    """A tests/ directory, or files following test_*.py / *_test.py naming."""
    found = []
    for dirpath, dirnames, _ in os.walk(PROJECT_ROOT):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in dirnames:
            if name.lower() in TEST_DIRS:
                found.append(
                    os.path.relpath(os.path.join(dirpath, name), PROJECT_ROOT).replace(
                        "\\", "/"
                    )
                )

    for path in files:
        base = os.path.basename(path)
        if base.startswith("test_") or base.endswith("_test.py"):
            found.append(path)

    return bool(found), sorted(set(found))


def _count_definitions(trees):
    """
    Raw definition and import counts across every parsed module.

    Counted with ast.walk, so nested functions and inner classes are
    included; this is a size metric, not the reference analysis performed
    by the dead-code tool.
    """
    functions = 0
    classes = 0
    imports = 0
    imports_per_file = {}

    for module, tree in trees.items():
        file_imports = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions += 1
            elif isinstance(node, ast.ClassDef):
                classes += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                imports += 1
                file_imports += 1
        imports_per_file[module] = file_imports

    return functions, classes, imports, imports_per_file


def _reach_sizes(graph, files):
    """Number of modules transitively reachable from each module."""
    sizes = {}
    for start in files:
        seen = set()
        stack = list(graph.get(start, []))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(graph.get(node, []))
        seen.discard(start)
        sizes[start] = len(seen)
    return sizes


def _acyclic_graph(graph, files):
    """
    Drop every edge whose endpoints share a strongly connected component.

    What remains is guaranteed acyclic (edges only cross between distinct
    components, and the condensation of a digraph is a DAG), which is what
    makes the longest-chain metric well defined on a project that contains
    circular imports. Cyclic paths are excluded rather than broken
    arbitrarily, so the metric never depends on which edge we chose to cut.
    """
    component_id = {}
    for index, component in enumerate(
        circular_import_detector._tarjan_sccs(graph, files)
    ):
        for node in component:
            component_id[node] = index

    return {
        node: [
            target
            for target in graph.get(node, [])
            if component_id.get(target) != component_id.get(node)
        ]
        for node in files
    }


def _longest_chain(graph, files):
    """
    Longest dependency chain, computed on the acyclic remainder.

    Kahn's algorithm produces a topological order; a single reverse pass
    then fills best[n] = 1 + max(best[successor]) with a successor pointer
    so the winning chain can be reconstructed. Both passes are iterative,
    so a deep graph cannot exhaust the recursion limit. Ties are broken
    lexicographically, making the result stable for a given source tree.
    """
    dag = _acyclic_graph(graph, files)

    indegree = {node: 0 for node in files}
    for node in files:
        for target in dag.get(node, []):
            indegree[target] = indegree.get(target, 0) + 1

    ready = sorted(node for node in files if indegree[node] == 0)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in dag.get(node, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()

    best = {node: 1 for node in files}
    nxt = {node: None for node in files}
    for node in reversed(order):
        for target in sorted(dag.get(node, [])):
            if best[target] + 1 > best[node]:
                best[node] = best[target] + 1
                nxt[node] = target

    if not best:
        return []

    start = min(files, key=lambda node: (-best[node], node))
    chain = []
    cursor = start
    while cursor is not None:
        chain.append(cursor)
        cursor = nxt[cursor]
    return chain


def _execution_flow(entry, graph, reach):
    """
    The principal execution path from one entry point.

    At each hop the next module is the direct dependency with the largest
    transitive reach (ties broken lexicographically), which follows the
    spine of the program rather than an arbitrary alphabetical edge. Each
    hop reports how many sibling dependencies were not followed, so the
    path is never mistaken for the module's only edge.

    When a module's dependencies concentrate in a *different* package at or
    above FLOW_COLLAPSE_FANOUT, the walk stops and reports that package as a
    single fan-out step instead of listing every module. Fan-out within the
    module's own package is not collapsed, because that is ordinary internal
    structure rather than a layer boundary worth summarising.
    """
    steps = [{"kind": "module", "path": entry, "others": 0}]
    visited = {entry}
    cursor = entry

    while len(steps) < FLOW_MAX_STEPS:
        options = [t for t in graph.get(cursor, []) if t not in visited]
        if not options:
            break

        grouped = {}
        for target in options:
            package = _package_of(target)
            if package != _package_of(cursor):
                grouped.setdefault(package, []).append(target)
        widest = (
            max(sorted(grouped), key=lambda pkg: (len(grouped[pkg]), pkg))
            if grouped
            else None
        )
        if widest is not None and len(grouped[widest]) >= FLOW_COLLAPSE_FANOUT:
            steps.append(
                {
                    "kind": "fanout",
                    "package": widest,
                    "count": len(grouped[widest]),
                    "others": len(options) - len(grouped[widest]),
                }
            )
            break

        nxt = min(options, key=lambda node: (-reach.get(node, 0), node))
        steps.append({"kind": "module", "path": nxt, "others": len(options) - 1})
        visited.add(nxt)
        cursor = nxt

    return steps


# ---------------------------------------------------------------------------
# Layer detection
# ---------------------------------------------------------------------------


def _detect_layers(files, graph, entry_points):
    """
    Assign every package a layer from its position in the dependency graph.

    Layers are derived, never hardcoded. Each package is described by three
    structural numbers - how many other packages import it (fan-in), how
    many it imports (fan-out), and how many modules it holds - and labelled
    by the first matching rule:

    1. Presentation / Entry Layer
       - the package contains a detected entry point. It is where execution
         begins.
    2. Isolated Modules
       - fan-in and fan-out are both zero: nothing connects it to the rest
         of the project.
    3. Foundation / Infrastructure Layer
       - fan-out is zero and fan-in is positive: depended upon by others,
         depends on nothing. The bottom of the stack.
    4. Orchestration Layer
       - imported by a presentation package and importing two or more
         packages itself: it receives control and distributes it.
    5. Shared Service Layer
       - fan-in of two or more: several unrelated packages rely on it.
    6. Tool / Plugin Layer
       - at least PLUGIN_PACKAGE_MODULES modules consumed by exactly one
         package: the fan-out shape of a plugin or tool collection.
    7. Supporting Layer
       - everything else: connected, but with no distinguishing shape.

    Responsibility text is generated from the same numbers, so a layer's
    stated purpose is a restatement of its measured position, not a guess
    about intent.
    """
    packages = {}
    for path in files:
        packages.setdefault(_package_of(path), []).append(path)

    fan_in = {pkg: set() for pkg in packages}
    fan_out = {pkg: set() for pkg in packages}
    for source in files:
        for target in graph.get(source, []):
            src_pkg = _package_of(source)
            dst_pkg = _package_of(target)
            if src_pkg != dst_pkg:
                fan_out[src_pkg].add(dst_pkg)
                fan_in.setdefault(dst_pkg, set()).add(src_pkg)

    entry_packages = {_package_of(path) for path in entry_points}

    # Modules of a package consumed by exactly one outside module: the
    # signature of a tool/plugin collection.
    single_consumer = {}
    for pkg, members in packages.items():
        consumers = set()
        consumed = set()
        for source in files:
            if _package_of(source) == pkg:
                continue
            for target in graph.get(source, []):
                if target in members:
                    consumers.add(source)
                    consumed.add(target)
        single_consumer[pkg] = (sorted(consumers), len(consumed))

    layers = []
    for pkg in sorted(packages):
        members = sorted(packages[pkg])
        incoming = sorted(fan_in.get(pkg, ()))
        outgoing = sorted(fan_out.get(pkg, ()))
        consumers, consumed_count = single_consumer[pkg]

        if pkg in entry_packages:
            entries = sorted(p for p in entry_points if _package_of(p) == pkg)
            name = "Presentation / Entry Layer"
            reason = f"contains detected entry point(s): {', '.join(entries)}"
        elif not incoming and not outgoing:
            name = "Isolated Modules"
            reason = "no cross-package dependency in either direction"
        elif not outgoing:
            name = "Foundation / Infrastructure Layer"
            reason = (
                f"imported by {len(incoming)} package(s) "
                f"({', '.join(_dotted(p) for p in incoming)}); imports none"
            )
        elif any(p in entry_packages for p in incoming) and len(outgoing) >= 2:
            name = "Orchestration Layer"
            reason = (
                f"imported by the entry package and imports {len(outgoing)} "
                f"package(s): {', '.join(_dotted(p) for p in outgoing)}"
            )
        elif len(incoming) >= 2:
            name = "Shared Service Layer"
            reason = (
                f"imported by {len(incoming)} package(s): "
                f"{', '.join(_dotted(p) for p in incoming)}"
            )
        elif consumed_count >= PLUGIN_PACKAGE_MODULES and len(consumers) == 1:
            name = "Tool / Plugin Layer"
            reason = (
                f"{consumed_count} of {len(members)} modules consumed by a "
                f"single module ({consumers[0]})"
            )
        else:
            name = "Supporting Layer"
            reason = (
                f"fan-in {len(incoming)}, fan-out {len(outgoing)}, "
                f"{len(members)} module(s)"
            )

        layers.append(
            {
                "package": pkg,
                "layer": name,
                "files": members,
                "reason": reason,
                "fan_in": incoming,
                "fan_out": outgoing,
            }
        )

    order = [
        "Presentation / Entry Layer",
        "Orchestration Layer",
        "Shared Service Layer",
        "Tool / Plugin Layer",
        "Foundation / Infrastructure Layer",
        "Supporting Layer",
        "Isolated Modules",
    ]
    layers.sort(key=lambda item: (order.index(item["layer"]), item["package"]))
    return layers


# ---------------------------------------------------------------------------
# Dead-code facts (classification rules reused from Phase 11.6)
# ---------------------------------------------------------------------------


def _dead_code_facts(files, trees, graph, entry_points, guard_called, unparseable):
    """
    Recompute the Phase 11.6 candidate sets for inclusion in this report.

    Every decision rule - exemptions, reference detection, confidence and
    module scoring - is called out of dead_code_detector rather than
    restated here, so the two tools cannot reach different verdicts. Only
    the loop that walks the definitions lives in this file.
    """
    reachable = dead_code_detector._reachable_modules(graph, entry_points)
    module_candidates = dead_code_detector._module_candidates(
        files, graph, entry_points, reachable, bool(entry_points), unparseable
    )
    candidate_modules = {item["module"] for item in module_candidates}

    definitions = []
    for module in sorted(trees):
        definitions.extend(dead_code_detector._collect_definitions(module, trees[module]))

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

    name_refs, attr_refs, import_refs = dead_code_detector._build_reference_index(trees)

    analyzed = []
    for definition in definitions:
        if dead_code_detector._exemption(definition, entry_points, guard_called):
            continue
        if dead_code_detector._has_external_reference(
            definition, name_refs, attr_refs, import_refs, importers
        ):
            continue
        analyzed.append(definition)

    unreferenced_classes = {
        (d["module"], d["name"]) for d in analyzed if d["kind"] == "class"
    }

    functions = []
    classes = []
    for definition in analyzed:
        if definition["kind"] == "method":
            if (definition["module"], definition["class_name"]) in unreferenced_classes:
                continue
        confidence, _ = dead_code_detector._confidence(
            definition, definition["module"] in candidate_modules
        )
        record = {
            "label": f"{definition['module']}::{definition['qualname']}",
            "confidence": confidence,
        }
        (classes if definition["kind"] == "class" else functions).append(record)

    functions.sort(key=lambda r: r["label"])
    classes.sort(key=lambda r: r["label"])
    return module_candidates, functions, classes


# ---------------------------------------------------------------------------
# Observations, recommendations, score
# ---------------------------------------------------------------------------


def _observations(facts):
    """
    Evidence-backed observations.

    Each rule fires only on a computed threshold and each carries the
    numbers that triggered it. There is no rule that produces a claim which
    cannot be checked against the sections above it.
    """
    out = []
    files = facts["files"]
    graph = facts["graph"]
    strong = facts["strong"]
    total = len(files)

    if not facts["entry_points"]:
        out.append(
            (
                "No entry point detected",
                "No module contains a __main__ guard or launcher evidence.",
            )
        )
    elif len(strong) == 1:
        out.append(
            (
                "Single entry-point architecture detected",
                f"Exactly one strong entry point: {strong[0]}.",
            )
        )
    else:
        out.append(
            (
                "Multiple entry points detected",
                f"{len(strong)} strong entry points: {', '.join(strong)}.",
            )
        )

    if total:
        hub = max(sorted(files), key=lambda p: len(graph.get(p, [])))
        hub_out = len(graph.get(hub, []))
        if hub_out >= max(2, int(total * CENTRAL_ROUTER_SHARE)):
            share = 100.0 * hub_out / total
            out.append(
                (
                    "Centralized routing architecture detected",
                    f"{hub} imports {hub_out} local modules "
                    f"({share:.0f}% of {total} modules), the highest in the project.",
                )
            )

    plugin_layers = [l for l in facts["layers"] if l["layer"] == "Tool / Plugin Layer"]
    for layer in plugin_layers:
        out.append(
            (
                "Tool / plugin architecture detected",
                f"{_dotted(layer['package'])}: {layer['reason']}.",
            )
        )

    shared = []
    for path in sorted(files):
        dependents = facts["dependents"].get(path, [])
        packages = {_package_of(d) for d in dependents}
        if (
            len(dependents) >= SHARED_SERVICE_DEPENDENTS
            and len(packages) >= SHARED_SERVICE_PACKAGES
        ):
            shared.append((len(dependents), len(packages), path))
    # Report only the most widely shared, so a large project cannot bury the
    # other observations under one per service module.
    for count, package_count, path in sorted(shared, reverse=True)[
        :SHARED_SERVICE_REPORTED
    ]:
        out.append(
            (
                "Shared service module detected",
                f"{path} is imported by {count} modules across "
                f"{package_count} packages.",
            )
        )

    if facts["cycles"]:
        first = facts["cycles"][0]
        out.append(
            (
                "Circular dependencies detected",
                f"{len(facts['cycles'])} cycle(s); Cycle #1: "
                f"{' -> '.join(first + [first[0]])}.",
            )
        )
    else:
        out.append(
            (
                "No circular dependency issues detected",
                f"{len(facts['files'])} modules and {facts['edges']} local "
                "relationships contain no cycle.",
            )
        )

    if facts["mean_deps"] < LOW_COUPLING_MEAN:
        out.append(
            (
                "Low coupling between modules",
                f"Average local dependencies per module is "
                f"{facts['mean_deps']:.1f}, below {LOW_COUPLING_MEAN:.1f}.",
            )
        )

    distinct_layers = {l["layer"] for l in facts["layers"]}
    if len(distinct_layers) >= LAYERED_MIN_LAYERS:
        out.append(
            (
                "Package structure follows layered organization",
                f"{len(distinct_layers)} distinct layers across "
                f"{len(facts['layers'])} packages.",
            )
        )

    isolated = facts["isolated"]
    if isolated and all(os.path.basename(p) == "__init__.py" for p in isolated):
        out.append(
            (
                "Isolated modules are package markers only",
                f"All {len(isolated)} isolated modules are __init__.py files.",
            )
        )
    elif isolated:
        real = [p for p in isolated if os.path.basename(p) != "__init__.py"]
        out.append(
            (
                "Disconnected modules present",
                f"{len(real)} non-marker module(s) have no local relationship: "
                f"{', '.join(real)}.",
            )
        )

    dead_total = (
        len(facts["dead_modules"]) + len(facts["dead_functions"]) + len(facts["dead_classes"])
    )
    if dead_total:
        out.append(
            (
                "Unused-code candidates present",
                f"{len(facts['dead_modules'])} module(s), "
                f"{len(facts['dead_functions'])} function(s) and "
                f"{len(facts['dead_classes'])} class(es) have no detected references.",
            )
        )
    else:
        out.append(
            (
                "No unused-code candidates detected",
                "Every module, function and class has a detected reference "
                "or a documented exemption.",
            )
        )

    if facts["unparseable"]:
        out.append(
            (
                "Unparseable sources present",
                f"{len(facts['unparseable'])} file(s) failed to parse and were "
                "excluded from analysis.",
            )
        )

    return out


def _recommendations(facts):
    """Recommendations derived only from findings computed above."""
    out = []

    if not facts["has_docs"]:
        out.append(("Add README.md.", "Documentation not detected at project root."))
    if not facts["has_tests"]:
        out.append(
            ("Add tests/.", "No test directory or test_*.py module detected.")
        )
    if not facts["entry_points"]:
        out.append(
            (
                "Add an explicit entry point.",
                "No module contains a __main__ guard or launcher evidence.",
            )
        )
    if facts["cycles"]:
        first = facts["cycles"][0]
        out.append(
            (
                "Break dependency cycle.",
                f"Cycle #1: {' -> '.join(first + [first[0]])}.",
            )
        )
    high = [
        c
        for c in facts["dead_modules"] + facts["dead_functions"] + facts["dead_classes"]
        if c["confidence"] == "High Candidate"
    ]
    if high:
        out.append(
            (
                "Review unused modules, functions and classes.",
                f"{len(high)} high-confidence candidate(s) with no detected "
                "reference.",
            )
        )
    real_isolated = [
        p for p in facts["isolated"] if os.path.basename(p) != "__init__.py"
    ]
    if real_isolated:
        out.append(
            (
                "Connect or remove disconnected modules.",
                f"{len(real_isolated)} module(s) with no local relationship: "
                f"{', '.join(real_isolated)}.",
            )
        )
    if facts["unparseable"]:
        out.append(
            (
                "Fix unparseable sources.",
                f"{len(facts['unparseable'])} file(s) failed to parse: "
                f"{', '.join(facts['unparseable'])}.",
            )
        )

    if not out:
        out.append(
            (
                "Architecture appears healthy. Continue modular development.",
                "No structural, dependency, entry-point or dead-code finding "
                "was triggered.",
            )
        )
    return out


def _health_score(facts):
    """
    Deterministic scoring rubric. Four categories, each 0-10, floored at 0.
    The overall score is their unweighted mean to one decimal place.

    STRUCTURE - packaging, documentation and tests
      start 10
      -2  no README at project root and no docs/ directory
      -2  no tests/ directory and no test_*.py / *_test.py module
      -2  no package directories (every module sits at the root)
      -1  one or more files failed to parse

    DEPENDENCY HEALTH - graph shape
      start 10
      -4  one or more circular import cycles exist
      -1  per additional cycle beyond the first
          (cycle penalties capped at -6 in total)
      -2  average local dependencies per module exceeds 5.0

    ENTRY POINT CLARITY - can the program be started unambiguously
      2   no entry point detected at all
      6   only likely/possible entry points, none strong
      10  exactly one strong entry point
      -1  per additional strong entry point, capped at -3
          (several launchers is workable but less unambiguous)

    MODULE ORGANIZATION - unused and disconnected code
      start 10
      -1  per high-confidence dead-code candidate, capped at -4
      -1  per two medium-confidence candidates, capped at -2
      -1  per isolated non-marker module, capped at -3
          (__init__.py package markers are never penalised)

    Every deduction is returned with the evidence that caused it, so a
    score can always be reconciled against the sections above it.
    """
    breakdown = {}

    structure = 10
    notes = []
    if not facts["has_docs"]:
        structure -= PENALTY_NO_README
        notes.append(f"-{PENALTY_NO_README} no README or docs/")
    if not facts["has_tests"]:
        structure -= PENALTY_NO_TESTS
        notes.append(f"-{PENALTY_NO_TESTS} no tests")
    if not facts["packages"]:
        structure -= PENALTY_NO_PACKAGES
        notes.append(f"-{PENALTY_NO_PACKAGES} no package directories")
    if facts["unparseable"]:
        structure -= PENALTY_UNPARSEABLE
        notes.append(f"-{PENALTY_UNPARSEABLE} unparseable file(s)")
    breakdown["Structure"] = (max(0, structure), notes)

    dependency = 10
    notes = []
    if facts["cycles"]:
        penalty = min(
            PENALTY_CYCLE_CAP,
            PENALTY_FIRST_CYCLE + PENALTY_EXTRA_CYCLE * (len(facts["cycles"]) - 1),
        )
        dependency -= penalty
        notes.append(f"-{penalty} {len(facts['cycles'])} circular import cycle(s)")
    if facts["mean_deps"] > HEAVY_COUPLING_MEAN:
        dependency -= PENALTY_HEAVY_COUPLING
        notes.append(
            f"-{PENALTY_HEAVY_COUPLING} average dependencies "
            f"{facts['mean_deps']:.1f} exceeds {HEAVY_COUPLING_MEAN:.1f}"
        )
    breakdown["Dependency Health"] = (max(0, dependency), notes)

    notes = []
    strong = facts["strong"]
    if not facts["entry_points"]:
        entry = ENTRY_SCORE_NONE
        notes.append(f"{ENTRY_SCORE_NONE} no entry point detected")
    elif not strong:
        entry = ENTRY_SCORE_WEAK
        notes.append(f"{ENTRY_SCORE_WEAK} no strong entry point")
    else:
        entry = ENTRY_SCORE_STRONG
        if len(strong) > 1:
            penalty = min(ENTRY_MULTI_PENALTY_CAP, len(strong) - 1)
            entry -= penalty
            notes.append(f"-{penalty} {len(strong)} strong entry points")
    breakdown["Entry Point Clarity"] = (max(0, entry), notes)

    organization = 10
    notes = []
    candidates = (
        facts["dead_modules"] + facts["dead_functions"] + facts["dead_classes"]
    )
    high = sum(1 for c in candidates if c["confidence"] == "High Candidate")
    medium = sum(1 for c in candidates if c["confidence"] == "Medium Candidate")
    if high:
        penalty = min(PENALTY_DEAD_HIGH_CAP, high)
        organization -= penalty
        notes.append(f"-{penalty} {high} high-confidence dead-code candidate(s)")
    if medium:
        penalty = min(PENALTY_DEAD_MEDIUM_CAP, medium // 2)
        if penalty:
            organization -= penalty
            notes.append(f"-{penalty} {medium} medium-confidence candidate(s)")
    real_isolated = [
        p for p in facts["isolated"] if os.path.basename(p) != "__init__.py"
    ]
    if real_isolated:
        penalty = min(PENALTY_ISOLATED_CAP, len(real_isolated))
        organization -= penalty
        notes.append(f"-{penalty} {len(real_isolated)} disconnected module(s)")
    breakdown["Module Organization"] = (max(0, organization), notes)

    overall = sum(value for value, _ in breakdown.values()) / float(len(breakdown))
    return breakdown, round(overall, 1)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _section(lines, title):
    lines.extend(["", "=" * 60, title, "=" * 60, ""])


def _bullets(items):
    return [f"- {item}" for item in items] if items else ["- (none)"]


def generate_architecture_report(args):
    saved_root = dead_code_detector.PROJECT_ROOT
    dead_code_detector.PROJECT_ROOT = PROJECT_ROOT
    try:
        files, trees, graph, unparseable = dead_code_detector._parse_project()
        if not files:
            return "No Python files found in project"
        entry_points, guard_called = dead_code_detector._entry_point_facts(
            files, trees, graph
        )
        dead_modules, dead_functions, dead_classes = _dead_code_facts(
            files, trees, graph, entry_points, guard_called, unparseable
        )
    finally:
        dead_code_detector.PROJECT_ROOT = saved_root

    dependents = {path: [] for path in files}
    for source in files:
        for target in graph.get(source, []):
            dependents.setdefault(target, []).append(source)
    for path in dependents:
        dependents[path] = sorted(set(dependents[path]))

    edges = sum(len(graph.get(path, [])) for path in files)
    dep_counts = [len(graph.get(path, [])) for path in files]
    dependent_counts = [len(dependents.get(path, [])) for path in files]
    mean_deps = module_relationship._mean(dep_counts)
    mean_dependents = module_relationship._mean(dependent_counts)

    records = []
    for path in files:
        deps = graph.get(path, [])
        deps_of = dependents.get(path, [])
        records.append(
            {
                "path": path,
                "dependency_count": len(deps),
                "dependent_count": len(deps_of),
                "total": len(deps) + len(deps_of),
                "classification": module_relationship._classify(
                    len(deps), len(deps_of), mean_deps, mean_dependents
                ),
            }
        )
    by_class = {}
    for record in records:
        by_class.setdefault(record["classification"], []).append(record)
    for group in by_class.values():
        group.sort(key=lambda r: (-r["total"], r["path"]))

    isolated = [r["path"] for r in by_class.get("Isolated", [])]

    components = circular_import_detector._circular_components(graph, files)
    raw_cycles, cycles_truncated = circular_import_detector._elementary_cycles(
        graph, files, circular_import_detector.MAX_CYCLES
    )
    seen = set()
    cycles = []
    for cycle in raw_cycles:
        canonical = circular_import_detector._canonical(cycle)
        if canonical not in seen:
            seen.add(canonical)
            cycles.append(list(canonical))
    cycles.sort(key=lambda c: (len(c), c))

    strong = sorted(p for p, c in entry_points.items() if c == "Strong Entry Point")
    likely = sorted(p for p, c in entry_points.items() if c == "Likely Entry Point")
    possible = sorted(p for p, c in entry_points.items() if c == "Possible Entry Point")
    roots = sorted(
        path
        for path in files
        if not dependents.get(path)
        and path not in entry_points
        and os.path.basename(path) != "__init__.py"
    )

    packages = sorted({_package_of(p) for p in files if _package_of(p) != "(root)"})
    layers = _detect_layers(files, graph, entry_points)
    reach = _reach_sizes(graph, files)
    total_functions, total_classes, total_imports, imports_per_file = _count_definitions(
        trees
    )
    has_docs, doc_evidence = _has_documentation()
    has_tests, test_evidence = _has_tests(files)

    facts = {
        "files": files,
        "graph": graph,
        "dependents": dependents,
        "edges": edges,
        "mean_deps": mean_deps,
        "entry_points": entry_points,
        "strong": strong,
        "cycles": cycles,
        "layers": layers,
        "isolated": isolated,
        "dead_modules": dead_modules,
        "dead_functions": dead_functions,
        "dead_classes": dead_classes,
        "unparseable": unparseable,
        "has_docs": has_docs,
        "has_tests": has_tests,
        "packages": packages,
    }

    observations = _observations(facts)
    recommendations = _recommendations(facts)
    breakdown, overall = _health_score(facts)

    lines = ["Project Architecture Report"]

    # 1. PROJECT OVERVIEW
    _section(lines, "1. PROJECT OVERVIEW")
    lines.extend(
        [
            f"Project:            {os.path.basename(PROJECT_ROOT) or PROJECT_ROOT}",
            f"Project Root:       {PROJECT_ROOT}",
            f"Python Files:       {len(files)}",
            f"Modules:            {len(files)}",
            f"Packages:           {len(packages)}",
        ]
    )
    lines.extend(f"  - {_dotted(p)}" for p in packages)
    lines.extend(
        [
            f"Entry Points:       {len(entry_points)}",
            f"Architecture Status: {'Healthy' if entry_points else 'Incomplete'}",
        ]
    )

    # 2. EXECUTION FLOW
    _section(lines, "2. EXECUTION FLOW")
    flow_entries = strong or likely or possible
    if not flow_entries:
        lines.append("No entry point detected; execution flow cannot be derived.")
    else:
        for entry in flow_entries[:FLOW_MAX_ENTRY_POINTS]:
            for step in _execution_flow(entry, graph, reach):
                if step["kind"] == "module":
                    suffix = (
                        f"   (+{step['others']} other direct dependencies)"
                        if step["others"]
                        else ""
                    )
                    lines.append(f"{step['path']}{suffix}")
                else:
                    suffix = (
                        f"   (+{step['others']} other direct dependencies)"
                        if step["others"]
                        else ""
                    )
                    lines.append(
                        f"{step['count']} modules in {_dotted(step['package'])}{suffix}"
                    )
                lines.append("  |")
                lines.append("  v")
            lines.pop()
            lines.pop()
            lines.append("")
        lines.pop()
        lines.append("Path follows the dependency with the largest transitive reach")
        lines.append("at each step; wide fan-out is collapsed to its package.")

    # 3. LAYER DETECTION
    _section(lines, "3. LAYER DETECTION")
    for layer in layers:
        lines.append(f"{layer['layer']}  [{_dotted(layer['package'])}]")
        lines.append("Files:")
        lines.extend(f"  - {path}" for path in layer["files"])
        lines.append(f"Responsibility: {layer['reason']}")
        lines.append("")
    lines.pop()

    # 4. MODULE IMPORTANCE
    _section(lines, "4. MODULE IMPORTANCE")
    lines.append(
        f"Project means: {mean_deps:.1f} dependencies, "
        f"{mean_dependents:.1f} dependents per module."
    )
    lines.append("")
    for label, key in (
        ("Core Modules", "Core / Central"),
        ("Highly Coupled Modules", "High Coupling"),
        ("Supporting Modules", "Supporting"),
        ("Leaf Modules", "Leaf"),
        ("Isolated Modules", "Isolated"),
    ):
        group = by_class.get(key, [])
        lines.append(f"{label} ({len(group)}):")
        if group:
            for record in group[:8]:
                lines.append(
                    f"  - {record['path']}  "
                    f"[deps {record['dependency_count']}, "
                    f"dependents {record['dependent_count']}, "
                    f"relationships {record['total']}]"
                )
            if len(group) > 8:
                lines.append(f"  ... and {len(group) - 8} more")
        else:
            lines.append("  - (none)")
        lines.append("")
    ranked = sorted(records, key=lambda r: (-r["total"], r["path"]))
    if ranked:
        top = ranked[0]
        lines.extend(
            [
                "Most Connected Module:",
                f"  {top['path']}",
                f"  Relationships: {top['total']}",
                "  Reason: highest combined dependency and dependent count.",
            ]
        )

    # 5. DEPENDENCY HEALTH
    _section(lines, "5. DEPENDENCY HEALTH")
    max_dep = max(records, key=lambda r: (r["dependency_count"], r["path"])) if records else None
    max_dependent = (
        max(records, key=lambda r: (r["dependent_count"], r["path"])) if records else None
    )
    lines.extend(
        [
            f"Total Relationships:        {edges}",
            f"Average Dependencies:       {mean_deps:.1f}",
            f"Average Dependents:         {mean_dependents:.1f}",
            f"Max Dependency Module:      {max_dep['path']} ({max_dep['dependency_count']})"
            if max_dep
            else "Max Dependency Module:      (none)",
            f"Max Dependent Module:       {max_dependent['path']} ({max_dependent['dependent_count']})"
            if max_dependent
            else "Max Dependent Module:       (none)",
            f"Circular Imports:           {len(cycles) if cycles else 'None'}",
            f"Strongly Connected Groups:  {len(components)}",
        ]
    )
    if cycles_truncated:
        lines.append(
            f"  (cycle output capped at {circular_import_detector.MAX_CYCLES})"
        )
    for number, cycle in enumerate(cycles[:5], start=1):
        lines.append(f"  Cycle #{number}: {' -> '.join(cycle + [cycle[0]])}")
    if len(cycles) > 5:
        lines.append(f"  ... and {len(cycles) - 5} more")
    lines.append(
        f"Status:                     {'Cycles Present' if cycles else 'No Cycles'}"
    )

    # 6. ENTRY POINT SUMMARY
    _section(lines, "6. ENTRY POINT SUMMARY")
    lines.append(f"Strong Entry Points ({len(strong)}):")
    lines.extend(f"  {item}" for item in _bullets(strong))
    lines.append(f"Likely Entry Points ({len(likely)}):")
    lines.extend(f"  {item}" for item in _bullets(likely))
    lines.append(f"Possible Entry Points ({len(possible)}):")
    lines.extend(f"  {item}" for item in _bullets(possible))
    lines.append(f"Root Modules Without Entry-Point Evidence ({len(roots)}):")
    lines.extend(f"  {item}" for item in _bullets(roots))

    # 7. DEAD CODE SUMMARY
    _section(lines, "7. DEAD CODE SUMMARY")
    all_dead = dead_modules + dead_functions + dead_classes
    if not all_dead:
        lines.append("Potential Dead Code:")
        lines.append("None detected.")
    else:
        lines.extend(
            [
                f"Potentially Unused Modules:   {len(dead_modules)}",
                f"Potentially Unused Functions: {len(dead_functions)}",
                f"Potentially Unused Classes:   {len(dead_classes)}",
                "",
                "High-Confidence Candidates:",
            ]
        )
        high = [c for c in dead_modules if c["confidence"] == "High Candidate"]
        high_defs = [
            c for c in dead_functions + dead_classes if c["confidence"] == "High Candidate"
        ]
        entries = [c["module"] for c in high] + [c["label"] for c in high_defs]
        lines.extend(f"  {item}" for item in _bullets(sorted(entries)))
        lines.append("")
        lines.append(
            "Candidates are static-analysis findings, not proof of dead code."
        )

    # 8. PROJECT COMPLEXITY METRICS
    _section(lines, "8. PROJECT COMPLEXITY METRICS")
    parsed = sorted(imports_per_file)
    largest = (
        max(parsed, key=lambda p: (imports_per_file[p], p)) if parsed else None
    )
    smallest = (
        min(parsed, key=lambda p: (imports_per_file[p], p)) if parsed else None
    )
    independent = (
        min(sorted(records, key=lambda r: r["path"]), key=lambda r: r["total"])
        if records
        else None
    )
    chain = _longest_chain(graph, files)
    lines.extend(
        [
            f"Total Functions:         {total_functions}",
            f"Total Classes:           {total_classes}",
            f"Total Imports:           {total_imports}",
            f"Average Imports/File:    {total_imports / float(len(files)):.1f}",
            f"Largest Module:          {largest} ({imports_per_file[largest]} imports)"
            if largest
            else "Largest Module:          (none)",
            f"Smallest Module:         {smallest} ({imports_per_file[smallest]} imports)"
            if smallest
            else "Smallest Module:         (none)",
            f"Most Independent Module: {independent['path']} ({independent['total']} relationships)"
            if independent
            else "Most Independent Module: (none)",
            f"Most Connected Module:   {ranked[0]['path']} ({ranked[0]['total']} relationships)"
            if ranked
            else "Most Connected Module:   (none)",
            f"Longest Dependency Chain: {len(chain)} modules",
        ]
    )
    if chain:
        lines.extend(f"  - {module}" for module in chain)
    if cycles:
        lines.append("  (cyclic paths excluded from this metric)")

    # 9. ARCHITECTURE OBSERVATIONS
    _section(lines, "9. ARCHITECTURE OBSERVATIONS")
    for title, evidence in observations:
        lines.extend([f"Observation: {title}", f"Evidence:    {evidence}", ""])
    lines.pop()

    # 10. RECOMMENDATIONS
    _section(lines, "10. RECOMMENDATIONS")
    for title, evidence in recommendations:
        lines.extend([f"Recommendation: {title}", f"Evidence:       {evidence}", ""])
    lines.pop()

    # 11. FINAL HEALTH SCORE
    _section(lines, "11. ARCHITECTURE SCORE")
    for label in (
        "Structure",
        "Dependency Health",
        "Entry Point Clarity",
        "Module Organization",
    ):
        value, notes = breakdown[label]
        lines.append(f"{label + ':':<22}{value}/10")
        lines.extend(f"    {note}" for note in notes)
    lines.append("")
    lines.append(f"{'Overall:':<22}{overall}/10")

    if doc_evidence:
        lines.extend(["", f"Documentation detected: {', '.join(doc_evidence)}"])
    if test_evidence:
        lines.append(f"Tests detected: {', '.join(test_evidence)}")
    if unparseable:
        lines.extend(["", "Unparseable Files (skipped):"])
        lines.extend(f"  - {path}" for path in unparseable)

    return "\n".join(lines)


register_tool(
    name="generate_architecture_report",
    description="Generate a complete architectural report of the current project",
    parameters={},
    handler=generate_architecture_report,
    risk_level="safe",
)
