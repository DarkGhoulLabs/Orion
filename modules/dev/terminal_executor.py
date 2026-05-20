import shlex
import subprocess

from core.intent_registry import register_tool


ALLOWED_COMMANDS = {"python", "pip", "git", "dir", "ls"}
MAX_OUTPUT_CHARS = 4000


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS]


def execute_terminal(args):
    command = None
    if isinstance(args, dict):
        command = args.get("command")

    if not command or not isinstance(command, str):
        return "Command not allowed"

    try:
        parts = shlex.split(command)
    except ValueError:
        return "Command not allowed"

    if not parts:
        return "Command not allowed"

    if parts[0].lower() not in ALLOWED_COMMANDS:
        return "Command not allowed"

    try:
        completed = subprocess.run(
            parts,
            shell=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error running command: {str(e)}"

    if completed.returncode == 0:
        return _truncate(completed.stdout or "")
    return _truncate(completed.stderr or completed.stdout or "")


register_tool(
    name="execute_terminal",
    description="Execute safe terminal commands",
    parameters={"command": "terminal command string"},
    handler=execute_terminal,
    risk_level="high",
)
