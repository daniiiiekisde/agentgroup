"""GitHub repository operations for AgentGroup agents."""
from __future__ import annotations
import base64
from typing import List, Dict, Optional
import requests


class GitHubOps:
    """Thin wrapper around the GitHub REST API v3."""

    API = "https://api.github.com"

    def __init__(self, token: str, owner: str, repo: str):
        self.owner = owner
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ------------------------------------------------------------------ #
    # Read helpers
    # ------------------------------------------------------------------ #

    def list_files(self, path: str = "", ref: str = "HEAD") -> List[Dict]:
        """List repository contents at *path*."""
        url = f"{self.API}/repos/{self.owner}/{self.repo}/contents/{path}"
        resp = requests.get(url, headers=self.headers, params={"ref": ref})
        resp.raise_for_status()
        return resp.json()

    def get_file(self, path: str, ref: str = "HEAD") -> str:
        """Return decoded file content as a string."""
        url = f"{self.API}/repos/{self.owner}/{self.repo}/contents/{path}"
        resp = requests.get(url, headers=self.headers, params={"ref": ref})
        resp.raise_for_status()
        data = resp.json()
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]

    def get_default_branch(self) -> str:
        url = f"{self.API}/repos/{self.owner}/{self.repo}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()["default_branch"]

    # ------------------------------------------------------------------ #
    # Write helpers
    # ------------------------------------------------------------------ #

    def create_branch(self, branch: str, from_branch: Optional[str] = None) -> str:
        """Create *branch* from *from_branch* (default: repo default branch)."""
        from_branch = from_branch or self.get_default_branch()
        # get sha of from_branch
        ref_url = f"{self.API}/repos/{self.owner}/{self.repo}/git/ref/heads/{from_branch}"
        sha = requests.get(ref_url, headers=self.headers).json()["object"]["sha"]
        payload = {"ref": f"refs/heads/{branch}", "sha": sha}
        resp = requests.post(
            f"{self.API}/repos/{self.owner}/{self.repo}/git/refs",
            json=payload,
            headers=self.headers,
        )
        resp.raise_for_status()
        return branch

    def update_file(
        self,
        path: str,
        content: str,
        message: str,
        sha: str,
        branch: str = "main",
    ) -> Dict:
        """Update an existing file on *branch*."""
        encoded = base64.b64encode(content.encode()).decode()
        payload = {"message": message, "content": encoded, "sha": sha, "branch": branch}
        url = f"{self.API}/repos/{self.owner}/{self.repo}/contents/{path}"
        resp = requests.put(url, json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def create_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str = "main",
    ) -> Dict:
        """Create a new file on *branch*."""
        encoded = base64.b64encode(content.encode()).decode()
        payload = {"message": message, "content": encoded, "branch": branch}
        url = f"{self.API}/repos/{self.owner}/{self.repo}/contents/{path}"
        resp = requests.put(url, json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: Optional[str] = None,
    ) -> Dict:
        """Open a pull request from *head* into *base*."""
        base = base or self.get_default_branch()
        payload = {"title": title, "body": body, "head": head, "base": base}
        url = f"{self.API}/repos/{self.owner}/{self.repo}/pulls"
        resp = requests.post(url, json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()
