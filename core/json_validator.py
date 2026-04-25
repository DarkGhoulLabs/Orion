import json
from typing import Any, Dict


def validate_and_parse_json(response: str) -> Dict[str, Any]:
    """
    Validate and parse an LLM JSON response into a safe plan structure.

    Returns a consistent shape:
    - success: True  -> { "success": True, "plan": validated_plan, "raw": parsed }
    - success: False -> { "success": False, "error": "...", "raw": response }
    """
    try:
        parsed = json.loads(response)
    except Exception:
        return {"success": False, "error": "Invalid JSON", "raw": response}

    if not isinstance(parsed, dict):
        return {"success": False, "error": "Invalid JSON structure", "raw": response}

    plan = parsed.get("plan")
    if not isinstance(plan, list) or not plan:
        return {"success": False, "error": "Invalid plan structure", "raw": response}

    validated_plan = []
    for item in plan:
        if not isinstance(item, dict):
            continue

        intent = item.get("intent")
        if not isinstance(intent, str) or not intent:
            continue

        arguments = item.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}

        validated_plan.append({"intent": intent, "arguments": arguments})

    if not validated_plan:
        return {"success": False, "error": "Invalid plan structure", "raw": response}

    return {"success": True, "plan": validated_plan, "raw": parsed}

