import ast
import os

from core.intent_registry import register_tool
import modules.files.file_manager as file_manager


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IGNORED_DIRS = {".git", "__pycache__", ".venv"}


def _resolve_path(path):
    if os.path.isabs(path):
        return os.path.normpath(path)
    for base in (file_manager.CURRENT_DIR, PROJECT_ROOT):
        candidate = os.path.normpath(os.path.join(base, path))
        if os.path.isfile(candidate):
            return candidate
    return os.path.normpath(os.path.join(PROJECT_ROOT, path))


def _path_to_module(filepath):
    rel = os.path.relpath(filepath, PROJECT_ROOT)
    if rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace("\\", ".").replace("/", ".")


def _parse_imports(source):
    tree = ast.parse(source)
    imports = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
                for alias in node.names:
                    if alias.name != "*":
                        imports.add(f"{node.module}.{alias.name}")

    return sorted(imports)


def _file_imports_target(source, target_module):
    return target_module in _parse_imports(source)


def _iter_python_files():
    for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for filename in filenames:
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def _risk_level(dependent_count):
    if dependent_count <= 2:
        return "Low"
    if dependent_count <= 5:
        return "Medium"
    return "High"


def _format_list(items):
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def analyze_dependencies(args):
    path = None
    if isinstance(args, dict):
        path = args.get("path")

    if not path or not isinstance(path, str):
        return "File not found"

    filepath = _resolve_path(path)
    if not os.path.isfile(filepath):
        return "File not found"
    if not filepath.endswith(".py"):
        return "Not a Python source file"

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        imports = _parse_imports(source)
    except SyntaxError:
        return "Not a Python source file"
    except Exception:
        return "File not found"

    target_module = _path_to_module(filepath)
    display_path = os.path.relpath(filepath, PROJECT_ROOT).replace("\\", "/")

    imported_by = []
    for py_file in _iter_python_files():
        if os.path.normpath(py_file) == os.path.normpath(filepath):
            continue
        try:
            with open(py_file, "r", encoding="utf-8", errors="replace") as f:
                other_source = f.read()
            if _file_imports_target(other_source, target_module):
                rel = os.path.relpath(py_file, PROJECT_ROOT).replace("\\", "/")
                imported_by.append(rel)
        except (SyntaxError, OSError):
            continue

    imported_by.sort()
    risk = _risk_level(len(imported_by))

    return (
        "Dependency Report\n\n"
        "File:\n"
        f"{display_path}\n\n"
        "Imports:\n"
        f"{_format_list(imports)}\n\n"
        "Imported By:\n"
        f"{_format_list(imported_by)}\n\n"
        "Risk Level:\n"
        f"{risk}"
    )


register_tool(
    name="analyze_dependencies",
    description="Analyze dependencies of a Python file",
    parameters={"path": "Python file path"},
    handler=analyze_dependencies,
    risk_level="safe",
)
