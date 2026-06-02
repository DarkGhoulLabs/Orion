from core.intent_registry import register_tool
from core.memory_manager import get_active_project


def show_active_project(args):
    project = get_active_project()
    if not project:
        return "No active project remembered."

    return (
        "Active Project:\n"
        f"{project.get('name', '')}\n\n"
        "Path:\n"
        f"{project.get('path', '')}\n\n"
        "Last Summary:\n"
        f"{project.get('summary', '')}\n\n"
        "Updated:\n"
        f"{project.get('updated_at', '')}"
    )


register_tool(
    name="show_active_project",
    description="Show information about the currently remembered project",
    parameters={},
    handler=show_active_project,
    risk_level="safe",
)
