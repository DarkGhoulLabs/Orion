import httpx
from core.prompt_manager import build_system_prompt

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"

def ask_orion(user_input: str, mode="plan"):
    system_prompt = build_system_prompt(mode=mode)
    full_prompt = system_prompt + "\nUser: " + user_input

    payload = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": 256,
            "temperature": 0.2
        }
    }

    try:
        response = httpx.post(OLLAMA_URL, json=payload, timeout=180)
    except httpx.ReadTimeout:
        return "LLM timeout, try again"

    try:
        data = response.json()
    except Exception:
        print("LLM response JSON parse error")
        print("Status:", response.status_code)
        print("Body:", response.text)
        return "Error: Unexpected LLM response format"

    if isinstance(data, dict) and "response" in data:
        return data["response"]

    if isinstance(data, dict) and "message" in data:
        message = data.get("message")
        if isinstance(message, dict) and "content" in message:
            return message["content"]

    print("Unexpected LLM response format (debug):", data)
    return "Error: Unexpected LLM response format"