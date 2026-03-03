import httpx
from core.prompt_manager import build_system_prompt

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "mistral"

def ask_orion(user_input: str)->str:
    system_prompt = build_system_prompt()
    full_prompt = system_prompt + "\nUser: " + user_input

    payload = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "stream": False
    }

    resposnse = httpx.post(OLLAMA_URL, json=payload, timeout=60)

    return resposnse.json()["response"]