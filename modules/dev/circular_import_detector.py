"""
Phase 11.5 - Circular Import Detection.

Deterministic, static-analysis-only detection of circular import cycles in
the current project's local Python dependency graph.

Circular imports are a pure graph property, so they are established
algorithmically: Tarjan's strongly connected components locate the
circular regions, and Johnson's algorithm enumerates the elementary
cycles inside each one. No project code is imported or executed and the
LLM is not consulted.

Both algorithms are implemented iteratively so deep dependency graphs
cannot exhaust the recursion limit, and Johnson's algorithm is
output-sensitive rather than brute-force path enumeration.
"""

import ast
import os

from core.intent_registry import register_tool


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules"}

# Safety bound on enumerated elementary cycles. The number of elementary
# cycles in a graph can be exponential in the node count even though
# Johnson's algorithm is polynomial *per cycle*, so output is capped.
# Strongly connected components are always reported in full, so the
# circular regions of the project remain visible even when truncated.
MAX_CYCLES = 500


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


def _build_graph():
    """
    Build the local dependency graph: A -> B means A imports B.

    Edges are deduplicated per source, self-edges are dropped, and only
    imports resolving to real project files are kept (standard library,
    third-party and unresolvable names are ignored).
    """
    python_files = list(_iter_python_files())
    module_index = _build_module_index(python_files)
    graph = {}
    unparseable = []
    display_files = sorted(_posix_rel(path) for path in python_files)

    for filepath in python_files:
        source_rel = _posix_rel(filepath)
        targets = set()
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
            imported = _imported_modules(filepath, source)
        except (SyntaxError, OSError, ValueError, RecursionError):
            graph[source_rel] = []
            unparseable.append(source_rel)
            continue

        for name in imported:
            target = _resolve_local(name, module_index)
            # A self-edge is not a circular import; drop it here so it can
            # never reach cycle detection.
            if target and target != source_rel:
                targets.add(target)

        graph[source_rel] = sorted(targets)

    edge_count = sum(len(graph.get(path, [])) for path in display_files)
    return display_files, graph, edge_count, sorted(unparseable)


def _subgraph(graph, nodes):
    """Adjacency restricted to `nodes`, sorted for deterministic traversal."""
    node_set = set(nodes)
    return {
        node: sorted(t for t in graph.get(node, []) if t in node_set)
        for node in sorted(node_set)
    }


def _tarjan_sccs(graph, nodes):
    """
    Tarjan's strongly connected components, iterative.

    Returns a list of components, each a sorted list of module paths.
    Component order and contents are deterministic for a given graph.
    """
    node_set = set(nodes)
    index = {}
    low = {}
    on_stack = {}
    stack = []
    components = []
    counter = 0

    for root in sorted(node_set):
        if root in index:
            continue

        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        work = [(root, iter(graph.get(root, [])))]

        while work:
            node, neighbours = work[-1]
            descended = False

            for neighbour in neighbours:
                if neighbour not in node_set:
                    continue
                if neighbour not in index:
                    index[neighbour] = low[neighbour] = counter
                    counter += 1
                    stack.append(neighbour)
                    on_stack[neighbour] = True
                    work.append((neighbour, iter(graph.get(neighbour, []))))
                    descended = True
                    break
                if on_stack.get(neighbour):
                    low[node] = min(low[node], index[neighbour])

            if descended:
                continue

            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])

            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))

    return components


def _circular_components(graph, nodes):
    """
    Strongly connected components that are genuinely circular.

    A component is circular only when it holds at least two modules, which
    guarantees a path from every member back to itself. Single-module
    components are never circular here because self-edges were dropped
    during graph construction.
    """
    return sorted(
        (comp for comp in _tarjan_sccs(graph, nodes) if len(comp) > 1),
        key=lambda comp: (len(comp), comp),
    )


def _unblock(node, blocked, blocked_map):
    """Iterative unblock step of Johnson's algorithm."""
    pending = [node]
    while pending:
        current = pending.pop()
        if current in blocked:
            blocked.discard(current)
            pending.extend(sorted(blocked_map[current]))
            blocked_map[current] = set()


def _elementary_cycles(graph, nodes, limit):
    """
    Johnson's algorithm for elementary circuits, iterative.

    Each elementary cycle is emitted exactly once. Rotations cannot be
    duplicated because the start vertex is removed from consideration once
    every cycle through it has been reported.

    Returns (cycles, truncated) where each cycle is a list of module paths
    in traversal order (the closing repeat of the first module is not
    included).
    """
    cycles = []
    truncated = False
    pending = list(_circular_components(_subgraph(graph, nodes), nodes))

    while pending:
        component = pending.pop()
        sub = _subgraph(graph, component)
        start = min(component)

        path = [start]
        blocked = {start}
        closed = set()
        blocked_map = {node: set() for node in component}
        work = [(start, iter(sub.get(start, [])))]

        while work:
            node, neighbours = work[-1]
            descended = False

            for neighbour in neighbours:
                if neighbour == start:
                    cycles.append(list(path))
                    closed.update(path)
                    if len(cycles) >= limit:
                        truncated = True
                        break
                elif neighbour not in blocked:
                    path.append(neighbour)
                    blocked.add(neighbour)
                    closed.discard(neighbour)
                    work.append((neighbour, iter(sub.get(neighbour, []))))
                    descended = True
                    break

            if truncated:
                break
            if descended:
                continue

            if node in closed:
                _unblock(node, blocked, blocked_map)
            else:
                for neighbour in sub.get(node, []):
                    blocked_map[neighbour].add(node)

            work.pop()
            path.pop()

        if truncated:
            break

        # Every cycle through `start` has been found; drop it and recurse
        # into whatever components survive in the remainder.
        remaining = [node for node in component if node != start]
        if remaining:
            pending.extend(_circular_components(_subgraph(graph, remaining), remaining))

    return cycles, truncated


def _canonical(cycle):
    """
    Rotate a cycle to begin at its lexicographically smallest module.

    A -> B -> C -> A and C -> A -> B -> C are the same cycle; normalising
    the rotation makes that identity explicit and keeps output stable.
    """
    pivot = cycle.index(min(cycle))
    return tuple(cycle[pivot:] + cycle[:pivot])


def _format_list(items):
    if not items:
        return ["- (none)"]
    return [f"- {item}" for item in items]


def detect_circular_imports(args):
    python_files, graph, edge_count, unparseable = _build_graph()
    if not python_files:
        return "No Python files found in project"

    components = _circular_components(graph, python_files)
    raw_cycles, truncated = _elementary_cycles(graph, python_files, MAX_CYCLES)

    seen = set()
    cycles = []
    for cycle in raw_cycles:
        canonical = _canonical(cycle)
        if canonical in seen:
            continue
        seen.add(canonical)
        cycles.append(list(canonical))
    cycles.sort(key=lambda c: (len(c), c))

    involved = sorted({module for comp in components for module in comp})

    lines = ["Circular Import Detection", "", "Circular Imports:"]

    if not components:
        lines.extend(["- None", "", "No circular imports detected.", ""])
    else:
        lines.append(
            f"- {len(cycles)} cycle{'s' if len(cycles) != 1 else ''} detected"
        )
        lines.append(
            f"- {len(components)} strongly connected "
            f"component{'s' if len(components) != 1 else ''}"
        )
        if truncated:
            lines.append(
                f"- output capped at {MAX_CYCLES} cycles; "
                "components below list every circular module"
            )
        lines.append("")

        for number, cycle in enumerate(cycles, start=1):
            chain = cycle + [cycle[0]]
            lines.append(f"Cycle #{number}")
            lines.append(chain[0])
            lines.extend(f"    -> {module}" for module in chain[1:])
            lines.extend(["", f"Cycle Length: {len(cycle)}", "", "Modules Involved:"])
            lines.extend(_format_list(sorted(cycle)))
            lines.extend(["", "Relationships:"])
            lines.extend(
                f"- {chain[i]} -> {chain[i + 1]}" for i in range(len(chain) - 1)
            )
            lines.append("")

        lines.append("Strongly Connected Components (2+ modules):")
        lines.append("")
        for number, component in enumerate(components, start=1):
            lines.append(f"Component #{number} ({len(component)} modules):")
            lines.extend(_format_list(component))
            member_set = set(component)
            internal = [
                f"- {source} -> {target}"
                for source in component
                for target in graph.get(source, [])
                if target in member_set
            ]
            lines.append("Internal Relationships:")
            lines.extend(internal if internal else ["- (none)"])
            lines.append("")

    if unparseable:
        lines.extend(["Unparseable Files (skipped):"])
        lines.extend(f"- {path}" for path in unparseable)
        lines.append("")

    status = "Circular Imports Detected" if components else "No Circular Imports Detected"
    lines.extend(
        [
            "Summary:",
            f"Python Files: {len(python_files)}",
            f"Local Dependency Relationships: {edge_count}",
            f"Circular Import Cycles: {len(cycles)}",
            f"Modules Involved in Cycles: {len(involved)}",
            f"Status: {status}",
        ]
    )
    return "\n".join(lines)


register_tool(
    name="detect_circular_imports",
    description="Detect circular imports in the current project's Python dependency graph",
    parameters={},
    handler=detect_circular_imports,
    risk_level="safe",
)
