TOOLS = {}

def register_tool(name, description, parameters, handler, risk_level="safe"):
    TOOLS[name] = {
        "description": description,
        "parameters": parameters,
        "handler": handler,
        "risk_level": risk_level
    }

def get_tool(name):
    tool = TOOLS.get(name)
    if tool:
        return tool

    # Intent aliases for tools implemented via file_action.
    # Keeps existing tool mappings intact (e.g. "file_action").
    base = TOOLS.get("file_action")
    if base:
        file_intents = {
            "list_files",
            "change_directory",
            "delete_file",
            "create_folder",
            "rename_file",
            "move_file",
        }
        if name in file_intents:
            # Map individual file intents to the existing file_action tool
            # using the same handler and risk_level.
            return base

    return None

def get_all_tools():
    return TOOLS