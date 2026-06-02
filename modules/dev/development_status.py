from core.intent_registry import register_tool
from core.memory_manager import get_active_project, get_active_task, get_current_file


def show_development_ststus(args):
    project = get_active_project() or {}
    project_name = project.get("name", "") if isinstance(project, dict) else ""

    current_file = get_current_file() or ""
    active_task = get_active_task() or ""

    return (
        "Development Status\n\n"
        "Project:\n"
        f"{project_name}\n\n"
        "Current File:\n"
        f"{current_file}\n\n"
        "Active Task:\n"
        f"{active_task}"
    )


register_tool(
    name="show_development_ststus",
    description="Show current development context",
    parameters={},
    handler=show_development_ststus,
    risk_level="safe",
)

