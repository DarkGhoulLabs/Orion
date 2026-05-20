import os
import shutil

from core.intent_registry import register_tool
import modules.files.file_manager as file_manager


FOLDERS = {
    "images": {".jpg", ".jpeg", ".png"},
    "text": {".txt"},
    "code": {".py"},
    "others": set(),
}


def organize_files(args):
    target = file_manager.CURRENT_DIR
    counts = {folder: 0 for folder in FOLDERS}

    for folder in FOLDERS:
        os.makedirs(os.path.join(target, folder), exist_ok=True)

    for entry in os.listdir(target):
        src = os.path.join(target, entry)
        if not os.path.isfile(src):
            continue
        if entry in FOLDERS:
            continue

        ext = os.path.splitext(entry)[1].lower()
        dest_folder = "others"
        for folder, exts in FOLDERS.items():
            if folder != "others" and ext in exts:
                dest_folder = folder
                break

        dest = os.path.join(target, dest_folder, entry)
        shutil.move(src, dest)
        counts[dest_folder] += 1

    if sum(counts.values()) == 0:
        return "Moved 0 files"

    parts = [f"{counts[folder]} files to {folder}" for folder in FOLDERS if counts[folder] > 0]
    return "Moved " + ", ".join(parts)


register_tool(
    name="organize_files",
    description="Organize files in current directory by type",
    parameters=(),
    handler=organize_files,
    risk_level="moderate",
)
