"""Git repository management."""

import shutil
import subprocess
from pathlib import Path

from gitops_lite.config import StackConfig, ensure_repos_dir


class GitError(Exception):
    pass


def is_local_repo(repo: str) -> bool:
    """Check if repo is a local path."""
    return Path(repo).exists() or repo.startswith(("/", "./", "../"))


def ensure_repo(stack: StackConfig) -> Path:
    """Get repo path (local or cloned remote)."""
    # Local repo - use directly
    if is_local_repo(stack.repo):
        local_path = Path(stack.repo).resolve()
        if not local_path.exists():
            raise GitError(f"Local path does not exist: {local_path}")
        return local_path

    # Remote repo - clone/update to cache
    ensure_repos_dir()
    if not stack.cache_path:
        raise GitError(f"No cache_path for stack '{stack.name}'")

    repo_path = Path(stack.cache_path)
    if not repo_path.exists():
        _clone_repo(stack.repo, stack.branch, repo_path)
    else:
        _update_repo(stack.branch, repo_path)

    return repo_path


def _clone_repo(repo_url: str, branch: str, target_path: Path) -> None:
    try:
        subprocess.run(
            ["git", "clone", "--branch", branch, "--single-branch", repo_url, str(target_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitError(f"Clone failed: {e.stderr}") from e
    except FileNotFoundError:
        raise GitError("git not found") from None


def _update_repo(branch: str, repo_path: Path) -> None:
    try:
        subprocess.run(["git", "fetch", "--all"], cwd=repo_path, capture_output=True, text=True, check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], cwd=repo_path, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise GitError(f"Update failed: {e.stderr}") from e


def get_current_commit(repo_path: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_path, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def check_for_updates(stack: StackConfig) -> tuple[bool, str | None, str | None]:
    """Check for updates. Returns (has_updates, old_commit, new_commit)."""
    # Local repos always trigger re-processing
    if is_local_repo(stack.repo):
        local_path = Path(stack.repo).resolve()
        if local_path.exists():
            current = get_current_commit(local_path)
            return (True, current, current)
        return (False, None, None)

    # Remote repos - check cache
    if not stack.cache_path:
        return (False, None, None)

    repo_path = Path(stack.cache_path)
    if not repo_path.exists():
        return (False, None, None)

    old_commit = get_current_commit(repo_path)

    try:
        subprocess.run(["git", "fetch", "--all"], cwd=repo_path, capture_output=True, text=True, check=True)
        result = subprocess.run(["git", "rev-parse", "--short", f"origin/{stack.branch}"], cwd=repo_path, capture_output=True, text=True, check=True)
        new_commit = result.stdout.strip()
    except subprocess.CalledProcessError:
        return (False, old_commit, None)

    return (old_commit != new_commit, old_commit, new_commit)


def cleanup_repo(stack: StackConfig) -> bool:
    """Remove cached repo."""
    if not stack.cache_path:
        return False
    repo_path = Path(stack.cache_path)
    if not repo_path.exists():
        return False
    try:
        shutil.rmtree(repo_path)
        return True
    except (OSError, PermissionError) as e:
        from rich.console import Console
        Console().print(f"[yellow]Warning: Failed to cleanup repo: {e}[/yellow]")
        return False
