import webbrowser
from core.intent_registry import register_tool

def open_website(args):
    url = args.get("url")

    if not url:
        return "No URL provided."

    if not url.startswith("http"):
        url = "https://" + url
    
    webbrowser.open(url)
    return f"Opened {url}"

register_tool(
    name="open_website",
    description="Open a website in the default browser.",
    parameters={
        "url": "Website URL to open"
    },
    handler=open_website,
    risk_level="safe"
)