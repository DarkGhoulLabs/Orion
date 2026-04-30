import os

from core.intent_registry import register_tool


IGNORED_DIRS = {".git", "__pycache__", ".venv"}


def analyze_project_structure(args):
    root = os.getcwd()
    max_depth = 2

    lines = []

    print("PROJECT ANALYZER CALLED")
    print("LINES:", lines)
    
    def _walk(current: str, depth: int):
        if depth > max_depth:
            return

        try:
            entries = sorted(os.listdir(current))
        except Exception:
            return

        for name in entries:
            if name in IGNORED_DIRS:
                continue

            full_path = os.path.join(current, name)
            indent = "    " * depth

            if os.path.isdir(full_path):
                lines.append(f"{indent}{name}/")
                _walk(full_path, depth + 1)
            else:
                lines.append(f"{indent}{name}")

    for name in sorted(os.listdir(root)):
        if name in IGNORED_DIRS:
            continue

        full_path = os.path.join(root, name)
        if os.path.isdir(full_path):
            lines.append(f"{name}/")
            _walk(full_path, 1)
        else:
            lines.append(name)

    return "\n".join(lines) if lines else "No project structure found"


register_tool(
    name="analyze_project",
    description="Analyze the structure of the entire project (folders and modules). Use this when user asks about project structure.",
    parameters=(),
    handler=analyze_project_structure,
    risk_level="safe",
)

