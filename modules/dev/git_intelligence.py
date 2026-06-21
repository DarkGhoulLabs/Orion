import os
import subprocess

from core.intent_registry import register_tool
import modules.files.file_manager as file_manager


def _run_git(args):
    return subprocess.run(
        args,
        shell=False,
        capture_output=True,
        text=True,
        cwd=file_manager.CURRENT_DIR,
        timeout=15,
    )


def _format_file_list(files):
    if not files:
        return "- (none)"
    return "\n".join(f"- {path}" for path in sorted(files))


def _build_summary(branch, modified, staged, untracked):
    parts = [f"On branch {branch or 'unknown'}"]
    if not modified and not staged and not untracked:
        parts.append("Working tree clean")
    else:
        if staged:
            parts.append(f"{len(staged)} staged file(s)")
        if modified:
            parts.append(f"{len(modified)} modified file(s)")
        if untracked:
            parts.append(f"{len(untracked)} untracked file(s)")
    return "; ".join(parts)


def analyze_git_status(args):
    check = _run_git(["git", "rev-parse", "--is-inside-work-tree"])
    if check.returncode != 0 or check.stdout.strip() != "true":
        return "Not a git repository"

    branch_result = _run_git(["git", "branch", "--show-current"])
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

    status_result = _run_git(["git", "status", "--porcelain"])
    if status_result.returncode != 0:
        return "Not a git repository"

    modified = set()
    staged = set()
    untracked = set()

    for line in status_result.stdout.splitlines():
        if not line.strip():
            continue

        if line.startswith("??"):
            untracked.add(line[3:].strip())
            continue

        index_status = line[0]
        worktree_status = line[1]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]

        if index_status != " ":
            staged.add(path)
        if worktree_status != " ":
            modified.add(path)

    summary = _build_summary(branch, modified, staged, untracked)

    return (
        "Git Status Report\n"
        f"Branch:\n{branch or '(detached or unknown)'}\n"
        "Modified Files:\n"
        f"{_format_file_list(modified)}\n"
        "Staged Files:\n"
        f"{_format_file_list(staged)}\n"
        "Untracked Files:\n"
        f"{_format_file_list(untracked)}\n"
        "Repository Summary:\n"
        f"{summary}"
    )


register_tool(
    name="analyze_git_status",
    description="Analyze current git repository status",
    parameters={},
    handler=analyze_git_status,
    risk_level="safe",
)


MAX_DIFF_CHARS = 2000


def _truncate_diff(text):
    if len(text) <= MAX_DIFF_CHARS:
        return text
    return text[:MAX_DIFF_CHARS] + "\n... (truncated)"


def analyze_git_diff(args):
    check = _run_git(["git", "rev-parse", "--is-inside-work-tree"])
    if check.returncode != 0 or check.stdout.strip() != "true":
        return "Not a git repository"

    names_result = _run_git(["git", "diff", "--name-only"])
    if names_result.returncode != 0:
        return "Not a git repository"

    modified_files = [line.strip() for line in names_result.stdout.splitlines() if line.strip()]
    if not modified_files:
        return "No modified files"

    sections = ["Git Diff Analysis", ""]

    for path in modified_files:
        diff_result = _run_git(["git", "diff", "--", path])
        preview = _truncate_diff(diff_result.stdout.strip() if diff_result.returncode == 0 else "")
        if not preview:
            preview = "(no diff output)"

        sections.extend([
            "Modified File:",
            path,
            "",
            "Diff Preview:",
            preview,
            "",
        ])

    sections.extend([
        "Summary:",
        f"{len(modified_files)} modified file(s) analyzed",
    ])

    return "\n".join(sections)


register_tool(
    name="analyze_git_diff",
    description="Analyze current git diff",
    parameters={},
    handler=analyze_git_diff,
    risk_level="safe",
)


def analyze_commit_history(args):
    check = _run_git(["git", "rev-parse", "--is-inside-work-tree"])
    if check.returncode != 0 or check.stdout.strip() != "true":
        return "Not a git repository"

    log_result = _run_git(["git", "log", "--oneline", "-n", "10"])
    if log_result.returncode != 0:
        return "Not a git repository"

    commits = []
    for line in log_result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        commit_hash = parts[0]
        message = parts[1] if len(parts) > 1 else ""
        commits.append((commit_hash, message))

    if not commits:
        return "No commits found"

    lines = ["Commit History", ""]
    for commit_hash, message in commits:
        lines.append(f"{commit_hash} {message}")

    lines.extend([
        "",
        "Summary:",
        f"Last {len(commits)} commit(s) analyzed",
    ])
    return "\n".join(lines)


register_tool(
    name="analyze_commit_history",
    description="Analyze recent git commits",
    parameters={},
    handler=analyze_commit_history,
    risk_level="safe",
)


_PREFIX_RULES = [
    ("command_router", "feat(core)", "improve command routing"),
    ("file_manager", "feat(files)", "improve file operations"),
    ("memory", "feat(memory)", "improve memory system"),
    ("git", "feat(git)", "improve git intelligence"),
]


def _infer_commit_prefix(modified_files):
    normalized = [path.replace("\\", "/").lower() for path in modified_files]
    for keyword, prefix, description in _PREFIX_RULES:
        for path in normalized:
            if keyword in path:
                return prefix, description
    return "feat", "update modified files"


def generate_commit_message(args):
    check = _run_git(["git", "rev-parse", "--is-inside-work-tree"])
    if check.returncode != 0 or check.stdout.strip() != "true":
        return "Not a git repository"

    names_result = _run_git(["git", "diff", "--name-only"])
    if names_result.returncode != 0:
        return "Not a git repository"

    modified_files = [line.strip() for line in names_result.stdout.splitlines() if line.strip()]
    if not modified_files:
        return "No modified files"

    prefix, description = _infer_commit_prefix(modified_files)
    message = f"{prefix}: {description}"
    file_lines = "\n".join(f"- {path}" for path in modified_files)

    return (
        "Suggested Commit Message\n"
        f"{message}\n\n"
        "Modified Files:\n"
        f"{file_lines}"
    )


register_tool(
    name="generate_commit_message",
    description="Generate a git commit message from current changes",
    parameters={},
    handler=generate_commit_message,
    risk_level="safe",
)


IGNORED_SCAN_DIRS = {".git", "__pycache__", ".venv"}
LARGE_FILE_BYTES = 10 * 1024 * 1024
MAX_LARGE_FILES = 10


def _parse_porcelain_status(output):
    modified = set()
    staged = set()
    untracked = set()

    for line in output.splitlines():
        if not line.strip():
            continue
        if line.startswith("??"):
            untracked.add(line[3:].strip())
            continue

        index_status = line[0]
        worktree_status = line[1]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]

        if index_status != " ":
            staged.add(path)
        if worktree_status != " ":
            modified.add(path)

    return modified, staged, untracked


def _find_large_files(root):
    large_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_SCAN_DIRS]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue
            if size > LARGE_FILE_BYTES:
                rel = os.path.relpath(full_path, root)
                size_mb = size / (1024 * 1024)
                large_files.append(f"{rel} ({size_mb:.1f} MB)")
            if len(large_files) >= MAX_LARGE_FILES:
                return large_files
    return large_files


def _build_health_recommendations(modified, staged, untracked, readme_exists, has_tests, large_files):
    recommendations = []
    if modified or staged or untracked:
        recommendations.append("Commit or stash pending changes to keep the working tree clean.")
    if not readme_exists:
        recommendations.append("Add a README.md to document the project.")
    if not has_tests:
        recommendations.append("Add a tests/ directory to improve project reliability.")
    if large_files:
        recommendations.append("Review large files and consider Git LFS or removing them from the repo.")
    if not recommendations:
        recommendations.append("Repository health looks good. Continue maintaining tests and documentation.")
    return recommendations


def analyze_repository_health(args):
    check = _run_git(["git", "rev-parse", "--is-inside-work-tree"])
    if check.returncode != 0 or check.stdout.strip() != "true":
        return "Not a git repository"

    root_result = _run_git(["git", "rev-parse", "--show-toplevel"])
    if root_result.returncode != 0:
        return "Not a git repository"
    repo_root = root_result.stdout.strip()

    status_result = _run_git(["git", "status", "--porcelain"])
    if status_result.returncode != 0:
        return "Not a git repository"

    modified, staged, untracked = _parse_porcelain_status(status_result.stdout)
    repo_name = os.path.basename(repo_root) or repo_root

    readme_exists = os.path.isfile(os.path.join(repo_root, "README.md"))
    has_tests = any(
        os.path.isdir(os.path.join(repo_root, name))
        for name in ("tests", "test")
    )

    large_files = _find_large_files(repo_root)
    recommendations = _build_health_recommendations(
        modified, staged, untracked, readme_exists, has_tests, large_files
    )

    large_lines = "\n".join(f"- {item}" for item in large_files) if large_files else "- (none)"
    rec_lines = "\n".join(f"- {item}" for item in recommendations)

    return (
        "Repository Health Report\n"
        f"Repository:\n{repo_name}\n"
        "Git Status:\n"
        f"- modified files: {len(modified)}\n"
        f"- staged files: {len(staged)}\n"
        f"- untracked files: {len(untracked)}\n"
        "Documentation:\n"
        f"{'Present' if readme_exists else 'Missing'}\n"
        "Tests:\n"
        f"{'Present' if has_tests else 'Missing'}\n"
        "Large Files:\n"
        f"{large_lines}\n"
        "Recommendations:\n"
        f"{rec_lines}"
    )


register_tool(
    name="analyze_repository_health",
    description="Analyze repository health",
    parameters={},
    handler=analyze_repository_health,
    risk_level="safe",
)


def _extract_suggested_message(commit_report):
    if not commit_report.startswith("Suggested Commit Message"):
        return "feat: update repository"
    lines = commit_report.split("\n")
    if len(lines) > 1 and lines[1].strip():
        return lines[1].strip()
    return "feat: update repository"


def prepare_repository_commit(args):
    status_report = analyze_git_status(args)
    if status_report == "Not a git repository":
        return status_report

    status_result = _run_git(["git", "status", "--porcelain"])
    modified, staged, untracked = _parse_porcelain_status(status_result.stdout)

    if not modified and not untracked:
        return "Repository is clean. Nothing to commit."

    commit_report = generate_commit_message(args)
    suggested_message = _extract_suggested_message(commit_report)

    return (
        "Repository Ready for Commit\n\n"
        "Status:\n"
        f"{status_report}\n\n"
        "Suggested Commit Message:\n"
        f"{suggested_message}\n\n"
        "Suggested Commands:\n"
        "git add .\n"
        f'git commit -m "{suggested_message}"'
    )


register_tool(
    name="prepare_repository_commit",
    description="Prepare repository for commit",
    parameters={},
    handler=prepare_repository_commit,
    risk_level="safe",
)
