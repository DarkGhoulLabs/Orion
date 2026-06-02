from core.intent_registry import register_tool
from core.memory_manager import get_recent_commands


def show_recent_activity(args):
    commands = get_recent_commands(limit=10)
    if not commands:
        return "Recent Activity:\n\n(no commands yet)"

    lines = ["Recent Activity:", ""]
    for i, cmd in enumerate(commands, start=1):
        lines.append(f"{i}. {cmd}")
    return "\n".join(lines)


register_tool(
    name="show_recent_activity",
    description="Show recent user commands and workflows",
    parameters={},
    handler=show_recent_activity,
    risk_level="safe",
)
