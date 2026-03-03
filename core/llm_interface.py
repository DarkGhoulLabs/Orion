import httpx
from core.prompt_manager import SYSTEM_PROMPT

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "mistral"

def ask_orion(user_input: str)->str:
    full_prompt = SYSTEM_PROMPT + "\nUser: " + user_input

    payload = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "stream": False
    }

    resposnse = httpx.post(OLLAMA_URL, json=payload, timeout=60)

    result = resposnse.json()
    return result["response"]