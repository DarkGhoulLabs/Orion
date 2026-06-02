from core.intent_registry import register_tool
from core.memory_manager import (
    get_active_project,
    get_active_task,
    get_current_file,
    get_current_goal,
    get_recent_commands,
)


def show_workspace(args):
    project = get_active_project() or {}
    project_name = project.get("name") if isinstance(project, dict) else None

    current_file = get_current_file()
    active_task = get_active_task()
    current_goal = get_current_goal()
    recent = get_recent_commands(limit=5)

    lines = [
        "Workspace Context",
        "",
        "Project:",
        str(project_name) if project_name else "None",
        "",
        "Current File:",
        str(current_file) if current_file else "None",
        "",
        "Active Task:",
        str(active_task) if active_task else "None",
        "",
        "Current Goal:",
        str(current_goal) if current_goal else "None",
        "",
        "Recent Activity:",
    ]

    if recent:
        for i, cmd in enumerate(recent, start=1):
            lines.append(f"{i}. {cmd}")
    else:
        lines.append("None")

    return "\n".join(lines)


register_tool(
    name="show_workspace",
    description="Show complete ORION workspace context",
    parameters={},
    handler=show_workspace,
    risk_level="safe",
)

