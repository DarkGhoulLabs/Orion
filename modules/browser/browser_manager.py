import webbrowser
from core.intent_registry import register_intent

def open_website(args):
    url = args.get("url", "google.com")

    if not url.startswith("http"):
        url = "https://" + url
    
    webbrowser.open(url)
    return f"Opened {url}"

register_intent("open_website", open_website)