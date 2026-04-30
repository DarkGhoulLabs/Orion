import os

from core.intent_registry import register_tool


def read_file(args):
    path = None
    if isinstance(args, dict):
        path = args.get("path")

    if not path or not isinstance(path, str):
        return "File not found"

    if not os.path.exists(path):
        return "File not found"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(3000)
        return content
    except Exception as e:
        return f"Error reading file: {str(e)}"


register_tool(
    name="read_file",
    description="Read contents of a file",
    parameters={"path": "file path"},
    handler=read_file,
    risk_level="safe",
)

