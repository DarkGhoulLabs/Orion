import json
import re

from core.intent_registry import get_tool
from core.state_manager import set_pending, get_pending, clear_pending
from core.argument_validator import validate_arguments

import modules.browser.browser_manager
import modules.files.file_manager


def route_command(orion_response: str):
    pending = get_pending()
    if pending:
        #print("DEBUG: Inside confrimation block")
        if pending.get("type") == "plan_resume":
            #print("DEBUG: Step confrimation branch entered")
            if "yes" in orion_response.lower():
                plan = pending["plan"]
                index = pending["current_index"]

                clear_pending()

                results = []
                step = plan[index]
                print(f"DEBUG STEP: {step}")
                tool = get_tool(step["intent"])
                if tool:
                    args = step.get("arguments", {})
                    validation = validate_arguments(step["intent"], args)
                    if not validation["success"]:
                        return f"Setp {index + 1} failed: Invalid arguments: {validation['error']}"
                    call_args = dict(validation["arguments"])
                    if step["intent"] in {"list_files", "change_directory", "delete_file"}:
                        call_args["action"] = step["intent"]
                    result = tool["handler"](call_args)
                    results.append(result)

                for step_offset, next_step in enumerate(plan[index + 1:], start=index + 1):
                    tool = get_tool(next_step["intent"])
                    if tool:
                        args = next_step.get("arguments", {})
                        validation = validate_arguments(next_step["intent"], args)
                        if not validation["success"]:
                            return f"Setp {step_offset + 1} failed: Invalid arguments: {validation['error']}"
                        call_args = dict(validation["arguments"])
                        if next_step["intent"] in {"list_files", "change_directory", "delete_file"}:
                            call_args["action"] = next_step["intent"]
                        result = tool["handler"](call_args)
                        results.append(result)
                return "\n".join(results)
            else:
                clear_pending()
                return "Plan cancelled."

    
    try:
        json_match = re.search(r"\{.*\}", orion_response, re.DOTALL)
        print(f"RAW LLM RESPONSE: {orion_response}")

        if not json_match:
            return "Failed to understand command"
        
        json_text = json_match.group()
        data = json.loads(json_text)
    except Exception as e:
        print("JSON parse error:",e)
        print("LLM Response:", orion_response)
        return "Failed to understand command."
    
    if "plan" in data:
        plan = data["plan"]

        results = []
        for i, step in enumerate(plan):
            tool = get_tool(step["intent"])
            if not tool:
                continue

            args = step.get("arguments", {})
            validation = validate_arguments(step["intent"], args)
            if not validation["success"]:
                return f"Setp {i + 1} failed: Invalid arguments: {validation['error']}"

            risk = tool.get("risk_level", "safe")

            if risk == "safe":
                    call_args = dict(validation["arguments"])
                    if step["intent"] in {"list_files", "change_directory", "delete_file"}:
                        call_args["action"] = step["intent"]
                    result = tool["handler"](call_args)
                    results.append(result)

            else:
                set_pending({
                    "type": "plan_resume",
                    "plan": plan,
                    "current_index": i
                })
                return f"Proposed Step:\n{step}\nApprove plan? (yes/no)"
            
        if len(results) == 1:
            return str(results[0])
        return "\n".join(str(r) for r in results if r is not None)
    
    intent = data.get("intent")
    args = data.get("arguments", {})

    tool = get_tool(intent)
    #print("DEBUG Registered intents:", get_handler.__globals__["INTENT_REGISTRY"].keys())

    if tool:
        validation = validate_arguments(intent, args)
        if not validation["success"]:
            return f"Invalid arguments: {validation['error']}"
        call_args = dict(validation["arguments"])
        if intent in {"list_files", "change_directory", "delete_file"}:
            call_args["action"] = intent
        result = tool["handler"](call_args)

        if isinstance(result, str) and result.startswith("CONFIRM_DELETE"):
            set_pending({
                "intent": intent,
                "arguments": args
            })
            return "Are you sure? Type YES to confirm"
        
        return result

    if intent == "chat":
        return args.get("message", "")
    
    return f"Intent '{intent}' not implemented yet"


