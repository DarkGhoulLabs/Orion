import ast
import os

from core.intent_registry import register_tool


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules"}


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


def _imported_modules(filepath, source):
    tree = ast.parse(source)
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


def _format_list(items):
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def _mean(values):
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def _classify(dependency_count, dependent_count, mean_deps, mean_dependents):
    """
    Deterministic classification (first matching rule wins):

    1. Isolated
       - local dependency_count == 0 AND local dependent_count == 0
    2. High Coupling
       - dependency_count > project mean of dependency counts
         AND dependent_count > project mean of dependent counts
    3. Core / Central
       - dependency_count > project mean of dependency counts
         OR dependent_count > project mean of dependent counts
    4. Leaf
       - dependency_count == 0
    5. Supporting
       - all remaining modules

    Thresholds are project-relative means, not ORION-specific constants.
    """
    high_deps = dependency_count > mean_deps
    high_dependents = dependent_count > mean_dependents

    if dependency_count == 0 and dependent_count == 0:
        return "Isolated"
    if high_deps and high_dependents:
        return "High Coupling"
    if high_deps or high_dependents:
        return "Core / Central"
    if dependency_count == 0:
        return "Leaf"
    return "Supporting"


def _build_graph():
    python_files = list(_iter_python_files())
    module_index = _build_module_index(python_files)
    graph = {}
    display_files = sorted(_posix_rel(path) for path in python_files)

    for filepath in python_files:
        source_rel = _posix_rel(filepath)
        targets = set()
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
            imported = _imported_modules(filepath, source)
        except (SyntaxError, OSError, ValueError):
            graph[source_rel] = []
            continue

        for name in imported:
            target = _resolve_local(name, module_index)
            if target and target != source_rel:
                targets.add(target)

        graph[source_rel] = sorted(targets)

    dependents = {path: [] for path in display_files}
    for source in display_files:
        for target in graph.get(source, []):
            dependents.setdefault(target, []).append(source)

    for path in dependents:
        dependents[path] = sorted(set(dependents[path]))

    return display_files, graph, dependents


def analyze_module_relationships(args):
    python_files, graph, dependents = _build_graph()
    if not python_files:
        return "No Python files found in project"

    dep_counts = [len(graph.get(path, [])) for path in python_files]
    dependent_counts = [len(dependents.get(path, [])) for path in python_files]
    mean_deps = _mean(dep_counts)
    mean_dependents = _mean(dependent_counts)

    records = []
    edge_count = 0
    for path in python_files:
        deps = graph.get(path, [])
        deps_of = dependents.get(path, [])
        edge_count += len(deps)
        classification = _classify(
            len(deps),
            len(deps_of),
            mean_deps,
            mean_dependents,
        )
        records.append(
            {
                "path": path,
                "dependencies": deps,
                "dependents": deps_of,
                "dependency_count": len(deps),
                "dependent_count": len(deps_of),
                "total": len(deps) + len(deps_of),
                "classification": classification,
            }
        )

    lines = ["Module Relationship Analysis", ""]
    for rec in records:
        lines.extend(
            [
                f"Module: {rec['path']}",
                "Dependencies:",
                _format_list(rec["dependencies"]),
                "Dependents:",
                _format_list(rec["dependents"]),
                f"Dependency Count: {rec['dependency_count']}",
                f"Dependent Count: {rec['dependent_count']}",
                f"Classification: {rec['classification']}",
                "",
            ]
        )

    ranked = sorted(records, key=lambda rec: (-rec["total"], rec["path"]))
    top5 = ranked[:5]
    highly_coupled = [rec for rec in records if rec["classification"] == "High Coupling"]
    isolated = [rec for rec in records if rec["classification"] == "Isolated"]

    lines.append("Most Connected Modules:")
    if top5:
        for i, rec in enumerate(top5, start=1):
            lines.append(f"{i}. {rec['path']} - {rec['total']} relationships")
    else:
        lines.append("- (none)")

    lines.extend(["", "Highly Coupled Modules:"])
    if highly_coupled:
        lines.extend(f"- {rec['path']}" for rec in highly_coupled)
    else:
        lines.append("- (none)")

    lines.extend(["", "Isolated Modules:"])
    if isolated:
        lines.extend(f"- {rec['path']}" for rec in isolated)
    else:
        lines.append("- (none)")

    most_connected_top = top5[0]["total"] if top5 else 0
    most_connected_names = [
        rec["path"] for rec in ranked if rec["total"] == most_connected_top
    ]

    lines.extend(
        [
            "",
            "Summary:",
            f"Python Files: {len(python_files)}",
            f"Total Local Relationships: {edge_count}",
            f"Most Connected: {', '.join(most_connected_names) if most_connected_names else '(none)'}",
            f"Highly Coupled: {', '.join(rec['path'] for rec in highly_coupled) if highly_coupled else '(none)'}",
            f"Isolated: {', '.join(rec['path'] for rec in isolated) if isolated else '(none)'}",
        ]
    )
    return "\n".join(lines)


register_tool(
    name="analyze_module_relationships",
    description="Analyze relationships between Python modules in the current project",
    parameters={},
    handler=analyze_module_relationships,
    risk_level="safe",
)
