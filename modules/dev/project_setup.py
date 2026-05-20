import os
import subprocess
import sys

from core.intent_registry import register_tool
import modules.files.file_manager as file_manager


def _run_command(parts, cwd):
    return subprocess.run(
        parts,
        shell=False,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=cwd,
    )


def _venv_python(project_dir):
    if os.name == "nt":
        return os.path.join(project_dir, ".venv", "Scripts", "python.exe")
    return os.path.join(project_dir, ".venv", "bin", "python")


def setup_project_environment(args):
    project_dir = file_manager.CURRENT_DIR
    venv_dir = os.path.join(project_dir, ".venv")
    requirements_path = os.path.join(project_dir, "requirements.txt")

    summary = []

    if not os.path.isdir(venv_dir):
        try:
            completed = _run_command(
                [sys.executable, "-m", "venv", ".venv"],
                cwd=project_dir,
            )
            if completed.returncode == 0:
                summary.append("venv created")
            else:
                err = (completed.stderr or completed.stdout or "").strip()
                return f"venv creation failed: {err}"
        except subprocess.TimeoutExpired:
            return "venv creation timed out"
        except Exception as e:
            return f"venv creation failed: {str(e)}"
    else:
        summary.append("venv already exists")

    if os.path.isfile(requirements_path):
        python_bin = _venv_python(project_dir)
        if not os.path.isfile(python_bin):
            return "venv python not found; cannot install requirements"

        try:
            completed = _run_command(
                [python_bin, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=project_dir,
            )
            if completed.returncode == 0:
                summary.append("requirements installed")
            else:
                err = (completed.stderr or completed.stdout or "").strip()
                summary.append(f"requirements install failed: {err}")
        except subprocess.TimeoutExpired:
            summary.append("requirements install timed out")
        except Exception as e:
            summary.append(f"requirements install failed: {str(e)}")
    else:
        summary.append("requirements.txt not found")

    return "; ".join(summary)


register_tool(
    name="setup_project_environment",
    description="Setup Python project environment",
    parameters={},
    handler=setup_project_environment,
    risk_level="high",
)
