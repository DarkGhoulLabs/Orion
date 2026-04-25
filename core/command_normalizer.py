from typing import Dict


_PHRASE_TO_COMMAND: Dict[str, str] = {
    # Navigation
    "go to": "change_directory",
    "open folder": "change_directory",
    "cd": "change_directory",
    # File listing
    "show files": "list_files",
    "list files": "list_files",
}


def normalize_command(command: str) -> str:
    """
    Normalize a raw user command into a standardized command keyword.

    Steps:
    - Lowercase the input
    - Trim leading/trailing whitespace
    - Collapse multiple internal spaces
    - Map known phrases/synonyms to canonical command keywords
    """
    if not isinstance(command, str):
        raise TypeError("command must be a string")

    normalized = " ".join(command.lower().split())

    # Check phrase mappings in order of decreasing phrase length
    # so that longer, more specific phrases match before shorter ones.
    for phrase in sorted(_PHRASE_TO_COMMAND.keys(), key=len, reverse=True):
        if not normalized.startswith(phrase):
            continue

        # Ensure phrase is exact match or followed by a space
        if len(normalized) == len(phrase) or normalized[len(phrase)] == " ":
            remainder = normalized[len(phrase):].lstrip()
            mapped = _PHRASE_TO_COMMAND[phrase]
            return f"{mapped} {remainder}" if remainder else mapped

    return normalized

