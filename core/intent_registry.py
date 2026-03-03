TOOLS = {}

def register_tool(name, description, parameters, handler, risk_level="safe"):
    TOOLS[name] = {
        "description": description,
        "parameters": parameters,
        "handler": handler,
        "risk_level": risk_level
    }

def get_tool(name):
    return TOOLS.get(name)

def get_all_tools():
    return TOOLS