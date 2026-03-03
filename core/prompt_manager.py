from core.intent_registry import get_all_tools

def build_system_prompt():
    tools = get_all_tools()

    tool_descriptions = ""
    for name, tool in tools.items():
        tool_descriptions += f"""
Tool Name: {name}
Description: {tool['description']}
Parameters: {tool['parameters']}
"""
    return f"""
You are ORION (Omni-Responsive Intelligent Operating System).

You must respond ONLY in valid JSON format.

If action is required, return:
{{
    "plan": [
        {{
            "intent": "<tool_name>",
            "arguments": {{ ... }}
        }},
        {{
            "intent": "<tool_name or chat>",
            "arguments": {{ ... }}
        }}
    ]
}}


If no tool is required:
{{
    "intent": "chat",
    "arguments": {{
        "message": "<response>"
    }}
}}

Available tools:
{tool_descriptions}
"""