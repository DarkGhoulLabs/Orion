import json
from core.intent_registry import get_handler

import modules.browser.browser_manager
import modules.files.file_manager

from core.state_manager import set_pending, get_pending, clear_pending

def route_command(orion_response: str):
    pending = get_pending()
    if pending:
        #print("DEBUG: Inside confrimation block")
        if "yes" in orion_response.lower():
            handler = get_handler(pending["intent"])
            confrimed_args = dict(pending["arguments"])
            confrimed_args["confrim"] = True
            clear_pending()
            return handler(confrimed_args)
        else:
            clear_pending()
            return "Cancelled"

    
    try:
        data = json.loads(orion_response)
    except json.JSONDecodeError:
        return "Failed to understand command."
    
    intent = data.get("intent")
    args = data.get("arguments", {})

    handler = get_handler(intent)
    #print("DEBUG Registered intents:", get_handler.__globals__["INTENT_REGISTRY"].keys())

    if handler:
        result = handler(args)

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