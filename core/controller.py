import json
import re

from core.llm_interface import ask_orion
from core.command_router import route_command
from core.agent_loop import run_agent_loop
from core.intent_registry import get_tool
from core.command_normalizer import normalize_command
from core.json_validator import validate_and_parse_json
from core.memory_manager import remember_command

def detect_intent(command: str):
    if "project" in command and ("analyze" in command or "structure" in command):
        return "analyze_project"
    return None

def execute_request(user_input):
    remember_command(user_input)
    normalized_command = normalize_command(user_input)

    # if normalized_command.startswith('list files'):
    #     tool = get_tool("file_action")
    #     return tool["handler"]({"action": "list_files"})

    # General "open <site>" handling
    if normalized_command.startswith("open "):
        parts = normalized_command.split(maxsplit=1)
        if len(parts) == 2 and parts[1]:
            site = parts[1]
            # Simple special-case for youtube wording
            if site == "youtube":
                site = "youtube.com"
            # If no dot is present, assume .com
            if "." not in site:
                site = f"{site}.com"
            tool = get_tool("open_website")
            return tool["handler"]({"url": site})

    single_word_keywords = {
        "organize",
        "multiple",
    }

    multi_word_keywords = {
        "figure out",
    }

    tokens = normalized_command.split()
    if any(word in tokens for word in single_word_keywords) or any(
        phrase in normalized_command for phrase in multi_word_keywords
    ):
        return run_agent_loop(user_input)
    
    intent = detect_intent(normalized_command)
    if intent:
        return route_command(json.dumps({
            "plan": [
                {
                    "intent": intent,
                    "arguments": {}
                }
            ]
        }))

    llm_response = ask_orion(user_input, mode="plan")
    json_payload = llm_response.strip()
    validated = validate_and_parse_json(json_payload)
    if not validated["success"]:
        print(f"JSON validation error: {validated['error']}")
        print(f"LLM response (debug): {llm_response!r}")
        return "Sorry couldn't understand that command."
    return route_command(json.dumps({"plan": validated["plan"]}))