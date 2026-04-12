"""GitHub REST API client — minimal surface for PR creation.

Uses httpx (already a transitive FastAPI dep) so no new library is needed.
"""

import httpx
import structlog

logger = structlog.get_logger()

GITHUB_API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize with status code and error message."""
        super().__init__(f"GitHub API error {status_code}: {message}")
        self.status_code = status_code


class GitHubClient:
    """Thin async GitHub REST client authenticated with a PAT."""

    def __init__(self, pat: str) -> None:
        """Initialize with a GitHub personal access token."""
        self._pat = pat

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        """Open a PR and return its HTML URL.

        Raises
        ------
        GitHubAPIError
            When the API returns a non-2xx response.
        """
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls"
        headers = {
            "Authorization": f"Bearer {self._pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=data, headers=headers)

        if response.status_code not in (200, 201):
            error_msg = response.json().get("message", response.text[:200])
            logger.error(
                "GitHub PR creation failed",
                status=response.status_code,
                owner=owner,
                repo=repo,
                error=error_msg,
            )
            raise GitHubAPIError(response.status_code, error_msg)

        pr_url: str = response.json()["html_url"]
        logger.info(
            "GitHub PR created",
            pr_url=pr_url,
            owner=owner,
            repo=repo,
            head=head_branch,
        )
        return pr_url
