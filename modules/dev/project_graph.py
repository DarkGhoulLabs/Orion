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


def show_project_graph(args):
    python_files = list(_iter_python_files())
    if not python_files:
        return "No Python files found in project"

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

    imported_by = {path: 0 for path in display_files}
    edge_count = 0
    for source in display_files:
        for target in graph.get(source, []):
            edge_count += 1
            imported_by[target] = imported_by.get(target, 0) + 1

    roots = [path for path in display_files if imported_by.get(path, 0) == 0]
    leaves = [path for path in display_files if not graph.get(path)]

    lines = ["Project Dependency Graph", "", "Root Files:"]
    if roots:
        lines.extend(f"- {path}" for path in roots)
    else:
        lines.append("- (none)")

    lines.extend(["", "Dependency Graph:", ""])
    for source in display_files:
        lines.append(source)
        targets = graph.get(source, [])
        if targets:
            lines.extend(f"    -> {target}" for target in targets)
        else:
            lines.append("    (no local dependencies)")
        lines.append("")

    lines.append("Leaf Modules:")
    if leaves:
        lines.extend(f"- {path}" for path in leaves)
    else:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "Summary:",
            f"Python Files: {len(display_files)}",
            f"Dependency Edges: {edge_count}",
            f"Root Files: {len(roots)}",
            f"Leaf Modules: {len(leaves)}",
        ]
    )
    return "\n".join(lines)


register_tool(
    name="show_project_graph",
    description="Show the project-wide Python dependency graph",
    parameters={},
    handler=show_project_graph,
    risk_level="safe",
)
