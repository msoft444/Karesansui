"""
github_sync.py

GitHub repository integration for the RAG knowledge base pipeline.

Pushes the converted Markdown files produced by document_parser to a private
GitHub repository while preserving the physical directory hierarchy
(chapter_N/chapter_N.md, chapter_N/section_M.md, etc.).

Environment variables (injected via docker-compose / .env):
    GITHUB_TOKEN  — Personal access token with repo write permission.
    GITHUB_REPO   — Full repository name in "owner/repo" format.
"""

import os
from pathlib import Path

from github import Github, GithubException, UnknownObjectException


def _get_github_client() -> Github:
    """
    Instantiate a PyGithub client authenticated with GITHUB_TOKEN.

    Raises:
        RuntimeError: If GITHUB_TOKEN is not set in the environment.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN environment variable is not set. "
            "Set it in .env to enable GitHub repository sync."
        )
    return Github(token)


def _get_repo(client: Github):
    """
    Return the target repository object for GITHUB_REPO.

    Raises:
        RuntimeError: If GITHUB_REPO is not set, the repository is not found,
                      or the repository is public (sync only allowed to private repos).
    """
    repo_name = os.environ.get("GITHUB_REPO")
    if not repo_name:
        raise RuntimeError(
            "GITHUB_REPO environment variable is not set. "
            "Set it in .env to enable GitHub repository sync."
        )
    try:
        repo = client.get_repo(repo_name)
    except UnknownObjectException as exc:
        raise RuntimeError(
            f"Repository '{repo_name}' was not found or the token lacks access."
        ) from exc
    if not repo.private:
        raise RuntimeError(
            f"Repository '{repo_name}' is public. "
            "Knowledge base sync is only permitted to private repositories."
        )
    return repo


def push_markdown_files(
    output_base_dir: str,
    repo_base_path: str = "knowledge_base",
    branch: str = "main",
    commit_message: str = "chore: update knowledge base",
) -> list[dict]:
    """
    Commit and push all Markdown files under *output_base_dir* to the GitHub
    repository specified by GITHUB_REPO, preserving the physical directory
    structure beneath *repo_base_path*.

    For each .md file the function either creates a new file or updates the
    existing one (if the content has changed), then commits it individually.
    Files whose content is unchanged are skipped to avoid empty commits.

    Args:
        output_base_dir: Local root directory produced by
                         document_parser.parse_and_split() (contains
                         chapter_N/... subdirectories).
        repo_base_path:  Target path prefix inside the repository
                         (default: "knowledge_base").
        branch:          Target branch to push to (default: "main").
        commit_message:  Base commit message.  The filename is appended
                         automatically to disambiguate per-file commits.

    Returns:
        A list of result dicts — one per .md file — containing:
            {
                "local_path":  str,   # absolute path of the local .md file
                "repo_path":   str,   # path inside the repository
                "status":      str,   # "created" | "updated" | "unchanged"
            }

    Raises:
        RuntimeError: When GITHUB_TOKEN or GITHUB_REPO are not set, or the
                      repository is inaccessible.
    """
    base_dir = Path(output_base_dir)
    md_files = sorted(base_dir.rglob("*.md"))
    if not md_files:
        return []

    client = _get_github_client()
    repo = _get_repo(client)

    results: list[dict] = []
    for md_path in md_files:
        relative = md_path.relative_to(base_dir)
        repo_path = f"{repo_base_path}/{relative}".replace("\\", "/")
        content = md_path.read_text(encoding="utf-8")

        status = _upsert_file(
            repo=repo,
            repo_path=repo_path,
            content=content,
            branch=branch,
            commit_message=f"{commit_message}: {relative}",
        )
        results.append(
            {
                "local_path": str(md_path),
                "repo_path": repo_path,
                "status": status,
            }
        )

    return results


def _upsert_file(
    repo,
    repo_path: str,
    content: str,
    branch: str,
    commit_message: str,
) -> str:
    """
    Create or update a single file in the repository.

    Returns:
        "created"   — file did not exist and was created.
        "updated"   — file existed and content differed; updated.
        "unchanged" — file existed and content was identical; skipped.

    Raises:
        GithubException: On unexpected GitHub API errors.
    """
    encoded = content.encode("utf-8")
    try:
        existing = repo.get_contents(repo_path, ref=branch)
        if existing.decoded_content == encoded:
            return "unchanged"
        repo.update_file(
            path=repo_path,
            message=commit_message,
            content=encoded,
            sha=existing.sha,
            branch=branch,
        )
        return "updated"
    except UnknownObjectException:
        # File does not yet exist — create it.
        repo.create_file(
            path=repo_path,
            message=commit_message,
            content=encoded,
            branch=branch,
        )
        return "created"
    except GithubException as exc:
        raise GithubException(exc.status, exc.data) from exc


def delete_document_files(
    repo_base_path: str,
    branch: str = "main",
    commit_message: str = "chore: remove knowledge base document",
) -> list[str]:
    """
    Delete all files under *repo_base_path* in the GitHub repository.

    Each file is deleted individually so that any partial failure does not
    prevent the remaining files from being removed.  Errors for individual
    files are silently suppressed; only authentication / repository access
    errors are propagated.

    Args:
        repo_base_path:  Path prefix inside the repository (e.g. "knowledge_base/doc-uuid").
        branch:          Target branch (default: "main").
        commit_message:  Commit message used for each deletion.

    Returns:
        A list of repository paths that were successfully deleted.

    Raises:
        RuntimeError: When GITHUB_TOKEN or GITHUB_REPO are not set, or the
                      repository is inaccessible.
    """
    client = _get_github_client()
    repo = _get_repo(client)
    deleted: list[str] = []
    failed: list[str] = []

    def _delete_tree(path: str) -> None:
        """Recursively delete all files under *path* in the repository."""
        try:
            contents = repo.get_contents(path, ref=branch)
        except UnknownObjectException:
            return  # Path does not exist — nothing to delete
        if not isinstance(contents, list):
            contents = [contents]
        for item in contents:
            if item.type == "dir":
                # Recurse into subdirectories before attempting deletion.
                _delete_tree(item.path)
            else:
                try:
                    repo.delete_file(
                        path=item.path,
                        message=commit_message,
                        sha=item.sha,
                        branch=branch,
                    )
                    deleted.append(item.path)
                except Exception as exc:  # noqa: BLE001
                    # Track the failure so the caller can decide whether to
                    # treat a partial delete as an error.
                    failed.append(item.path)

    _delete_tree(repo_base_path)

    if failed:
        raise RuntimeError(
            f"Failed to delete {len(failed)} file(s) from the repository: "
            + ", ".join(failed[:5])
            + (" …" if len(failed) > 5 else "")
        )

    return deleted
