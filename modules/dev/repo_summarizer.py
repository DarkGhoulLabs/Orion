import os

import httpx

from core.intent_registry import register_tool
from core.llm_interface import MODEL_NAME, OLLAMA_URL
from core.memory_manager import remember_project
import modules.files.file_manager as file_manager


IGNORED_DIRS = {".git", "__pycache__", ".venv"}
MAX_PY_FILES = 5
SNIPPET_CHARS = 600


def _extract_llm_text(data) -> str:
    if isinstance(data, dict) and "response" in data:
        return data["response"]
    if isinstance(data, dict) and "message" in data:
        message = data.get("message")
        if isinstance(message, dict) and "content" in message:
            return message["content"]
    return ""


def _read_text(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(limit) if limit else f.read()
        return content
    except Exception:
        return ""


def _build_structure(root):
    lines = []
    max_depth = 2

    def _walk(current, depth):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.listdir(current))
        except Exception:
            return
        for name in entries:
            if name in IGNORED_DIRS:
                continue
            full_path = os.path.join(current, name)
            rel = os.path.relpath(full_path, root)
            indent = "    " * depth
            if os.path.isdir(full_path):
                lines.append(f"{indent}{rel}/")
                _walk(full_path, depth + 1)
            else:
                lines.append(f"{indent}{rel}")

    for name in sorted(os.listdir(root)):
        if name in IGNORED_DIRS:
            continue
        full_path = os.path.join(root, name)
        if os.path.isdir(full_path):
            lines.append(f"{name}/")
            _walk(full_path, 1)
        else:
            lines.append(name)

    return "\n".join(lines)


def _collect_python_snippets(root):
    priority = [
        "cli/main.py",
        "core/controller.py",
        "core/command_router.py",
        "core/agent_loop.py",
        "core/llm_interface.py",
    ]
    snippets = []
    used = set()

    for rel in priority:
        full = os.path.join(root, rel.replace("/", os.sep))
        if os.path.isfile(full) and rel not in used:
            content = _read_text(full, SNIPPET_CHARS)
            if content:
                snippets.append(f"--- {rel} ---\n{content}")
                used.add(rel)
        if len(snippets) >= MAX_PY_FILES:
            return snippets

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, filename), root)
            if rel in used:
                continue
            content = _read_text(os.path.join(dirpath, filename), SNIPPET_CHARS)
            if content:
                snippets.append(f"--- {rel} ---\n{content}")
                used.add(rel)
            if len(snippets) >= MAX_PY_FILES:
                return snippets

    return snippets


def summarize_repository(args):
    root = file_manager.CURRENT_DIR
    context_parts = []

    structure = _build_structure(root)
    if structure:
        context_parts.append("PROJECT STRUCTURE:\n" + structure)

    readme_path = os.path.join(root, "README.md")
    if os.path.isfile(readme_path):
        readme = _read_text(readme_path, 2000)
        if readme:
            context_parts.append("README.md:\n" + readme)

    req_path = os.path.join(root, "requirements.txt")
    if os.path.isfile(req_path):
        requirements = _read_text(req_path, 1000)
        if requirements:
            context_parts.append("requirements.txt:\n" + requirements)

    snippets = _collect_python_snippets(root)
    if snippets:
        context_parts.append("CODE SNIPPETS:\n" + "\n\n".join(snippets))

    context = "\n\n".join(context_parts)
    if not context.strip():
        return "No repository context found."

    prompt = (
        "Summarize this repository:\n"
        "- purpose\n"
        "- architecture\n"
        "- main modules\n"
        "- workflows\n"
        "- technologies used\n\n"
        f"REPOSITORY CONTEXT:\n{context}"
    )

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 768,
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

    remember_project(
        os.path.basename(os.getcwd()),
        os.getcwd(),
        text,
    )
    return text


register_tool(
    name="summarize_repository",
    description="Summarize the current repository",
    parameters={},
    handler=summarize_repository,
    risk_level="safe",
)
