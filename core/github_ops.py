"""GitHub repository operations for AgentGroup agents.

Improvements:
- agents can now browse the full repo tree (list_tree)
- search_in_repo: search file contents via GitHub Search API
- get_pull_request / list_pull_requests: agents can inspect open PRs
- create_issue: agents can open issues directly
- add_pr_comment: agents can comment on PRs
- Token validation at construction time
- Timeout on all requests
"""
from __future__ import annotations
import base64
import logging
from typing import List, Dict, Optional
import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds


class GitHubOps:
    API = "https://api.github.com"

    def __init__(self, token: str, owner: str, repo: str):
        if not token:
            raise ValueError(
                "GitHub token is required. Set GITHUB_TOKEN in .env or pass it in the UI."
            )
        self.owner   = owner
        self.repo    = repo
        self.headers = {
            "Authorization":        f"Bearer {token}",
            "Accept":               "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, url: str, params: Optional[dict] = None) -> requests.Response:
        r = requests.get(url, headers=self.headers, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r

    def _post(self, url: str, payload: dict) -> requests.Response:
        r = requests.post(url, headers=self.headers, json=payload, timeout=_TIMEOUT)
        r.raise_for_status()
        return r

    def _put(self, url: str, payload: dict) -> requests.Response:
        r = requests.put(url, headers=self.headers, json=payload, timeout=_TIMEOUT)
        r.raise_for_status()
        return r

    # ── File operations ────────────────────────────────────────────────────────

    def list_files(self, path: str = "", ref: str = "HEAD") -> List[Dict]:
        url = f"{self.API}/repos/{self.owner}/{self.repo}/contents/{path}"
        return self._get(url, {"ref": ref}).json()

    def list_tree(self, ref: str = "HEAD", recursive: bool = True) -> List[Dict]:
        """List the full repo file tree."""
        url = f"{self.API}/repos/{self.owner}/{self.repo}/git/trees/{ref}"
        params = {"recursive": "1"} if recursive else {}
        data = self._get(url, params).json()
        return data.get("tree", [])

    def get_file(self, path: str, ref: str = "HEAD"):
        """Returns (content: str, sha: str)."""
        url  = f"{self.API}/repos/{self.owner}/{self.repo}/contents/{path}"
        data = self._get(url, {"ref": ref}).json()
        if isinstance(data, list):
            raise ValueError(f"'{path}' is a directory, not a file.")
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]

    def get_default_branch(self) -> str:
        url = f"{self.API}/repos/{self.owner}/{self.repo}"
        return self._get(url).json()["default_branch"]

    def create_branch(self, branch: str, from_branch: Optional[str] = None) -> str:
        from_branch = from_branch or self.get_default_branch()
        ref_url     = f"{self.API}/repos/{self.owner}/{self.repo}/git/ref/heads/{from_branch}"
        sha         = self._get(ref_url).json()["object"]["sha"]
        self._post(
            f"{self.API}/repos/{self.owner}/{self.repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": sha},
        )
        return branch

    def update_file(self, path: str, content: str, message: str,
                    sha: str, branch: str = "main") -> Dict:
        encoded = base64.b64encode(content.encode()).decode()
        return self._put(
            f"{self.API}/repos/{self.owner}/{self.repo}/contents/{path}",
            {"message": message, "content": encoded, "sha": sha, "branch": branch},
        ).json()

    def create_file(self, path: str, content: str, message: str,
                    branch: str = "main") -> Dict:
        encoded = base64.b64encode(content.encode()).decode()
        return self._put(
            f"{self.API}/repos/{self.owner}/{self.repo}/contents/{path}",
            {"message": message, "content": encoded, "branch": branch},
        ).json()

    # ── Pull Requests ─────────────────────────────────────────────────────────

    def create_pull_request(self, title: str, body: str, head: str,
                             base: Optional[str] = None) -> Dict:
        base = base or self.get_default_branch()
        return self._post(
            f"{self.API}/repos/{self.owner}/{self.repo}/pulls",
            {"title": title, "body": body, "head": head, "base": base},
        ).json()

    def list_pull_requests(self, state: str = "open") -> List[Dict]:
        url = f"{self.API}/repos/{self.owner}/{self.repo}/pulls"
        return self._get(url, {"state": state, "per_page": 20}).json()

    def get_pull_request(self, pr_number: int) -> Dict:
        url = f"{self.API}/repos/{self.owner}/{self.repo}/pulls/{pr_number}"
        return self._get(url).json()

    def add_pr_comment(self, pr_number: int, body: str) -> Dict:
        url = f"{self.API}/repos/{self.owner}/{self.repo}/issues/{pr_number}/comments"
        return self._post(url, {"body": body}).json()

    # ── Issues ─────────────────────────────────────────────────────────────────

    def create_issue(self, title: str, body: str,
                     labels: Optional[List[str]] = None) -> Dict:
        url = f"{self.API}/repos/{self.owner}/{self.repo}/issues"
        return self._post(url, {"title": title, "body": body,
                                "labels": labels or []}).json()

    def list_issues(self, state: str = "open") -> List[Dict]:
        url = f"{self.API}/repos/{self.owner}/{self.repo}/issues"
        return self._get(url, {"state": state, "per_page": 20}).json()

    # ── Search ─────────────────────────────────────────────────────────────────

    def search_in_repo(self, query: str) -> List[Dict]:
        """Search code inside the repo using GitHub Code Search API."""
        url    = f"{self.API}/search/code"
        params = {"q": f"{query} repo:{self.owner}/{self.repo}", "per_page": 10}
        headers = {**self.headers, "Accept": "application/vnd.github.text-match+json"}
        r = requests.get(url, headers=headers, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json().get("items", [])

    # ── Repo info ──────────────────────────────────────────────────────────────

    def get_repo_info(self) -> Dict:
        url = f"{self.API}/repos/{self.owner}/{self.repo}"
        return self._get(url).json()

    def get_commits(self, branch: Optional[str] = None, per_page: int = 10) -> List[Dict]:
        url    = f"{self.API}/repos/{self.owner}/{self.repo}/commits"
        params = {"per_page": per_page}
        if branch:
            params["sha"] = branch
        return self._get(url, params).json()
