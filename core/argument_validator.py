"""
Per-intent argument validation before tool execution.
Extend INTENT_RULES to add required fields and types.
"""

from copy import copy
from typing import Any, Dict, Tuple, Type

# intent -> (field_name, expected_type)[]
INTENT_RULES: Dict[str, Tuple[Tuple[str, Type[Any]], ...]] = {
    "change_directory": (("path", str),),
    "open_website": (("url", str),),
    "delete_file": (("path", str),),
    # list_files and unlisted intents: no required fields
}


def validate_arguments(intent: str, arguments: dict) -> dict:
    """
    Validate arguments for a tool intent. No filesystem or network checks.

    Success: {"success": True, "arguments": cleaned_arguments}
    Failure: {"success": False, "error": "error message"}
    """
    if not isinstance(arguments, dict):
        return {"success": False, "error": "arguments must be a dict"}

    cleaned = copy(arguments)
    rules = INTENT_RULES.get(intent)

    if not rules:
        return {"success": True, "arguments": cleaned}

    for field, expected_type in rules:
        if field not in cleaned:
            return {"success": False, "error": f'Missing required field: "{field}"'}

        value = cleaned[field]
        if value is None:
            return {"success": False, "error": f'Missing required field: "{field}"'}

        if not isinstance(value, expected_type):
            return {
                "success": False,
                "error": f'Invalid type for "{field}": expected {expected_type.__name__}',
            }

        if expected_type is str and not str(value).strip():
            return {"success": False, "error": f'"{field}" cannot be empty'}

    return {"success": True, "arguments": cleaned}
