import json
import os
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_PATH = os.path.join(
    BASE_DIR,
    "data",
    "memory_db",
    "memory.json",
)


def _ensure_dir():
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)


def load_memory():
    if not os.path.isfile(MEMORY_PATH):
        return {}

    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_memory(memory):
    if not isinstance(memory, dict):
        raise TypeError("memory must be a dict")

    _ensure_dir()
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def remember(key, value):
    memory = load_memory()
    memory[key] = value
    save_memory(memory)


def recall(key):
    return load_memory().get(key)


MAX_RECENT_COMMANDS = 20
RECENT_COMMANDS_KEY = "recent_commands"


def remember_command(command):
    if not command or not isinstance(command, str):
        return

    memory = load_memory()
    recent = memory.get(RECENT_COMMANDS_KEY, [])
    if not isinstance(recent, list):
        recent = []

    command = command.strip()
    if recent and recent[0] == command:
        return

    recent.insert(0, command)
    memory[RECENT_COMMANDS_KEY] = recent[:MAX_RECENT_COMMANDS]
    save_memory(memory)


def get_recent_commands(limit=10):
    recent = load_memory().get(RECENT_COMMANDS_KEY, [])
    if not isinstance(recent, list):
        return []
    return recent[:limit]


ACTIVE_PROJECT_KEY = "active_project"
CURRENT_FILE_KEY = "current_file"
ACTIVE_TASK_KEY = "active_task"
CURRENT_GOAL_KEY = "current_goal"


def remember_project(project_name, project_path, summary):
    memory = load_memory()
    memory[ACTIVE_PROJECT_KEY] = {
        "name": project_name,
        "path": project_path,
        "summary": summary,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_memory(memory)


def get_active_project():
    project = load_memory().get(ACTIVE_PROJECT_KEY)
    if isinstance(project, dict):
        return project
    return None


def remember_current_file(path):
    if not path or not isinstance(path, str):
        return
    remember(CURRENT_FILE_KEY, path)


def get_current_file():
    path = recall(CURRENT_FILE_KEY)
    return path if isinstance(path, str) and path else None


def remember_active_task(task_name):
    if not task_name or not isinstance(task_name, str):
        return
    remember(ACTIVE_TASK_KEY, task_name)


def get_active_task():
    task = recall(ACTIVE_TASK_KEY)
    return task if isinstance(task, str) and task else None


def remember_goal(goal):
    if not goal or not isinstance(goal, str):
        return
    remember(CURRENT_GOAL_KEY, goal)


def get_current_goal():
    goal = recall(CURRENT_GOAL_KEY)
    return goal if isinstance(goal, str) and goal else None
