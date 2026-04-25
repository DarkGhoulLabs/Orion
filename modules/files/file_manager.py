import os
import shutil
from core.intent_registry import register_tool

CURRENT_DIR = os.getcwd()

def file_action(args):
    print("FILE_MANAGER CALLED")
    print("ARGS RECEIVED:", args)
    
    global CURRENT_DIR

    action = str(args.get("action", "")).lower().replace(" ", "_")
    aliases = {
        "enter_directory": "change_directory",
        "go_to_directory": "change_directory",
        "move_directory": "change_directory",
        "open_directroy": "change_directory"
    }
    action = aliases.get(action, action)

    name = args.get("name")
    destination = args.get("destination")

    path = args.get("path") or args.get("directory") or args.get("folder")
    if path and not os.path.exists(path):
        possible = path + " folder"
        if os.path.exists(possible):
            path = possible

    #print("DEBUG: file action args", args)
    #print("DEBUG: action value", action)
    action = args.get("action")
    print("DEBUG: ACTION:", action)

    try:
        if action == "change_directory":
            if not path:
                return "Invalid path"
            path = path.strip('"').strip("'")
            path = os.path.normpath(path)
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            print("DEBUF PATH:", path)
            if not os.path.exists(path):
                return "Invalid path"
            os.chdir(path)
            CURRENT_DIR = path
            return f"Changed directory to {path}"
        
        elif action == "list_files":
            target = path if path else CURRENT_DIR
            if not os.path.exists(target):
                target = CURRENT_DIR
            files = os.listdir(target)
            if not files:
                return f"No files found in {target}"
            return "\n".join(files)
            
        elif action == "create_folder":
            full_path = os.path.join(CURRENT_DIR, name)
            os.makedirs(full_path, exist_ok=True)
            return f"Folder '{name}' created."
        
        
        elif action == "delete_file":
            delete_path = path or (os.path.join(CURRENT_DIR, name) if name else None)
            if not delete_path:
                return "File not found"
            delete_path = delete_path.strip('"').strip("'")
            delete_path = os.path.normpath(delete_path)
            if not os.path.isabs(delete_path):
                delete_path = os.path.join(os.getcwd(), delete_path)
            print("DEBUF PATH:", delete_path)
            if not os.path.exists(delete_path):
                return "File not found"
            os.remove(delete_path)
            return f"Deleted {delete_path}"
        
        elif action == "rename_file":
            new_name = args.get("new_name")
            os.rename(
                os.path.join(CURRENT_DIR, name),
                os.path.join(CURRENT_DIR, new_name)
            )
            return f"Renamed '{name}' to '{new_name}'"
        
        elif action == "move_file":
            shutil.move(
                os.path.join(CURRENT_DIR, name),
                destination
            )
            return f"Moved '{name}' to '{destination}'"
        
        else:
            return "Unknown file action"
    
    except Exception as e:
        return f"File error: {str(e)}"
    

def analyze_directory(args):
    target = CURRENT_DIR
    files = os.listdir(target)

    analysis = {
        "python": 0,
        "text": 0,
        "image": 0,
        "other": 0
    }

    for f in files:
        if f.endswith(".py"):
            analysis["python"] += 1
        elif f.endswith(".txt"):
            analysis["text"] += 1
        elif f.endswith((".png", ".jpg", ".jpeg")):
            analysis["images"] += 1
        else:
            analysis["other"] += 1
    
    return str(analysis)

register_tool(
    name="file_action",
    description="Perform file operations like create, delete, rename, move, list all files.",
    parameters={
        "action": "create_folder | list_files | delete_file | rename_file | move_file | change_directory",
        "name": "file or folder name",
        "new_name": "new file name if renaming",
        "destination": "target path for moving",
        "path": "directory path",
        "confirm": "boolean for deletion confirmation"
    },
    handler=file_action,
    risk_level="moderate"
)

register_tool(
    name="analyze_directory",
    description="Analyze files in the current directory and categorize them by type",
    parameters=(),
    handler=analyze_directory,
    risk_level="safe"
)