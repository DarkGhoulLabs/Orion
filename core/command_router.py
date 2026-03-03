import json
from core.intent_registry import get_tool
from core.state_manager import set_pending, get_pending, clear_pending

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
                tool = get_tool(step["intent"])
                results.append(tool["handler"](step.get("arguments", {})))

                for next_step in plan[index + 1:]:
                    tool = get_tool(next_step["intent"])
                    if tool:
                        results.append(tool["handler"](next_step.get("arguments", {})))
                return "\n".join(results)
            else:
                clear_pending()
                return "Plan cancelled."

    
    try:
        data = json.loads(orion_response)
    except json.JSONDecodeError:
        return "Failed to understand command."
    
    if "plan" in data:
        plan = data["plan"]

        for i, step in enumerate(plan):
            tool = get_tool(step["intent"])
            if not tool:
                continue

            risk = tool.get("risk_level", "safe")

            if risk == "safe":
                    tool["handler"](step.get("arguments", {}))

            else:
                set_pending({
                    "type": "plan_resume",
                    "plan": plan,
                    "current_index": i
                })
                return f"Proposed Step:\n{step}\nApprove plan? (yes/no)"
            
        return "Plan executed successfully"
    
    intent = data.get("intent")
    args = data.get("arguments", {})

    tool = get_tool(intent)
    #print("DEBUG Registered intents:", get_handler.__globals__["INTENT_REGISTRY"].keys())

    if tool:
        result = tool["handler"](args)

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