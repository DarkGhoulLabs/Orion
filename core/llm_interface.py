import httpx

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "mistral"

def ask_orion(prompt: str)->str:
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }

    resposnse = httpx.post(OLLAMA_URL, json=payload, timeout=60)

    result = resposnse.json()
    return result["response"]