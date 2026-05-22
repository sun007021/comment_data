from typing import Any

import requests


class GitHubClient:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("GITHUB_TOKEN is required")

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "comment-data-collector",
            }
        )

    def list_pull_requests(self, owner: str, repo: str, *, limit: int) -> list[dict[str, Any]]:
        return self._paginate(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            params={
                "state": "all",
                "sort": "created",
                "direction": "desc",
                "per_page": min(limit, 100),
            },
            limit=limit,
        )

    def list_pull_request_review_comments(
        self,
        owner: str,
        repo: str,
        *,
        pull_number: int,
    ) -> list[dict[str, Any]]:
        return self._paginate(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/comments",
            params={"per_page": 100},
        )

    def _paginate(
        self,
        url: str,
        *,
        params: dict[str, Any],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        next_params: dict[str, Any] | None = params

        while next_url and (limit is None or len(items) < limit):
            response = self._session.get(next_url, params=next_params, timeout=30)
            if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
                reset_at = response.headers.get("X-RateLimit-Reset", "unknown")
                raise RuntimeError(f"GitHub API rate limit exceeded. reset={reset_at}")
            response.raise_for_status()

            page = response.json()
            if not isinstance(page, list):
                raise RuntimeError(f"Unexpected GitHub API response from {next_url}")
            items.extend(page)

            next_url = response.links.get("next", {}).get("url")
            next_params = None

        if limit is not None:
            return items[:limit]
        return items
