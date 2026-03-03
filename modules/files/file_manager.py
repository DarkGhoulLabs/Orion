import os
import shutil
from core.intent_registry import register_intent

CURRENT_DIR = os.getcwd()

def file_action(args):
    global CURRENT_DIR

    action = str(args.get("action", "")).lower().strip()
    name = args.get("name")
    destination = args.get("destination")
    path = args.get("path")

    #print("DEBUG: file action args", args)
    #print("DEBUG: action value", action)

    try:
        if action == "change_directory":
            if os.path.isdir(path):
                CURRENT_DIR = path
                return f"Changed directory to {CURRENT_DIR}"
            else:
                return "Directory not found"
        
        elif action == "list_files":
            files = os.listdir(CURRENT_DIR) 
            return f"Files in {CURRENT_DIR}:" + ", ".join(files)
            
        elif action == "create_folder":
            full_path = os.path.join(CURRENT_DIR, name)
            os.makedirs(full_path, exist_ok=True)
            return f"Folder '{name}' created."
        
        
        elif action == "delete_file":
            full_path = os.path.join(CURRENT_DIR, name)
            if not os.path.exists(full_path):
                return "File not found."
            
            if not args.get("confrim"):
                return f"CONFIRM_DELETE: {name}"
            
            os.remove(full_path)
            return f"File '{name}' deleted."
        
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
    
register_intent("file_action", file_action)