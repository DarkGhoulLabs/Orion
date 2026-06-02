import os

import httpx

from core.intent_registry import register_tool
from core.llm_interface import MODEL_NAME, OLLAMA_URL
from core.memory_manager import get_current_file, remember_active_task, remember_current_file


def _extract_llm_text(data) -> str:
    if isinstance(data, dict) and "response" in data:
        return data["response"]
    if isinstance(data, dict) and "message" in data:
        message = data.get("message")
        if isinstance(message, dict) and "content" in message:
            return message["content"]
    return ""


def debug_code(args):
    path = None
    if isinstance(args, dict):
        path = args.get("path")

    if not path:
        path = get_current_file()
    if not path:
        return "No active file"
    if not isinstance(path, str) or not os.path.exists(path):
        return "File not found"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            code = f.read(8000)
    except Exception as e:
        return f"Error reading file: {str(e)}"

    prompt = (
        "You are debugging a real project.\n\n"
        "Analyze this code in context of a system.\n\n"
        "Identify:\n"
        "- real bugs (not generic suggestions)\n"
        "- incorrect assumptions\n"
        "- integration issues with other modules\n"
        "- possible causes of runtime failures\n\n"
        "Be specific. Avoid generic advice.\n\n"
        f"This is file: {path}\n\n"
        "CODE:\n"
        f"{code}"
    )

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 512,
            "temperature": 0.2,
        },
    }

    try:
        response = httpx.post(OLLAMA_URL, json=payload, timeout=180)
    except httpx.ReadTimeout:
        return "LLM timeout, try again"
    except Exception as e:
        return f"Error calling LLM: {str(e)}"

    try:
        data = response.json()
    except Exception:
        return "Error: Unexpected LLM response format"

    text = _extract_llm_text(data)
    if not text:
        return "Error: Unexpected LLM response format"
    remember_current_file(path)
    remember_active_task("debugging")
    return text


register_tool(
    name="debug_code",
    description="Analyze code and find issues",
    parameters={"path": "file path"},
    handler=debug_code,
    risk_level="safe",
)

