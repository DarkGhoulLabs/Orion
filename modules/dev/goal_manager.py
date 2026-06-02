from core.intent_registry import register_tool
from core.memory_manager import get_current_goal, remember_goal


def set_goal(args):
    goal = None
    if isinstance(args, dict):
        goal = args.get("goal")

    if not goal or not isinstance(goal, str):
        return "No active goal"

    goal = goal.strip()
    if not goal:
        return "No active goal"

    remember_goal(goal)
    return f"Current goal set:\n{goal}"


def show_goal(args):
    goal = get_current_goal()
    if not goal:
        return "No active goal"
    return f"Current Goal:\n{goal}"


register_tool(
    name="set_goal",
    description="Store the user's current goal",
    parameters={"goal": "goal text"},
    handler=set_goal,
    risk_level="safe",
)

register_tool(
    name="show_goal",
    description="Show the current stored goal",
    parameters=(),
    handler=show_goal,
    risk_level="safe",
)

