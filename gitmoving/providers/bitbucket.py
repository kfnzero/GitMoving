"""Bitbucket Cloud provider adapter using the Bitbucket REST API v2."""

from typing import List, Optional
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth

from ..auth.base import Credentials
from .base import BaseProvider, RepoInfo


class BitbucketProvider(BaseProvider):
    PROVIDER_NAME = "bitbucket"

    DEFAULT_API = "https://api.bitbucket.org/2.0"

    def __init__(self, creds: Credentials):
        super().__init__(creds)
        self._api_base = (creds.base_url or self.DEFAULT_API).rstrip("/")
        self._auth = HTTPBasicAuth(creds.username or "", creds.password or "")
        self._session = requests.Session()
        self._session.auth = self._auth
        self._session.headers.update({"Accept": "application/json"})

    def _get(self, path: str) -> dict:
        url = f"{self._api_base}/{path.lstrip('/')}"
        resp = self._session.get(url)
        if resp.status_code == 401:
            raise RuntimeError("Bitbucket authentication failed. Check username and App Password.")
        if resp.status_code == 404:
            raise ValueError(f"Resource not found: {url}")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict) -> dict:
        url = f"{self._api_base}/{path.lstrip('/')}"
        resp = self._session.post(url, json=json)
        if resp.status_code == 401:
            raise RuntimeError("Bitbucket authentication failed.")
        resp.raise_for_status()
        return resp.json()

    def validate_credentials(self) -> str:
        data = self._get("/user")
        return data.get("username") or data.get("account_id", "unknown")

    def get_repo(self, owner: str, repo_name: str) -> RepoInfo:
        try:
            data = self._get(f"/repositories/{owner}/{repo_name}")
        except ValueError as exc:
            raise ValueError(
                f"Repository '{owner}/{repo_name}' not found or not accessible."
            ) from exc

        clone_url = ""
        ssh_url = ""
        for link in data.get("links", {}).get("clone", []):
            if link["name"] == "https":
                clone_url = link["href"]
            elif link["name"] == "ssh":
                ssh_url = link["href"]

        return RepoInfo(
            name=data["name"],
            full_name=data["full_name"],
            clone_url=clone_url,
            ssh_url=ssh_url,
            private=data.get("is_private", True),
            default_branch=data.get("mainbranch", {}).get("name", "main"),
            description=data.get("description"),
        )

    def create_repo(
        self,
        name: str,
        owner: Optional[str] = None,
        description: Optional[str] = None,
        private: bool = True,
    ) -> RepoInfo:
        workspace = owner or self.creds.username
        payload = {
            "scm": "git",
            "name": name,
            "description": description or "",
            "is_private": private,
        }
        try:
            data = self._post(f"/repositories/{workspace}/{name}", payload)
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Failed to create Bitbucket repository '{name}': {exc}"
            ) from exc

        clone_url = ""
        ssh_url = ""
        for link in data.get("links", {}).get("clone", []):
            if link["name"] == "https":
                clone_url = link["href"]
            elif link["name"] == "ssh":
                ssh_url = link["href"]

        return RepoInfo(
            name=data["name"],
            full_name=data["full_name"],
            clone_url=clone_url,
            ssh_url=ssh_url,
            private=data.get("is_private", True),
            default_branch=data.get("mainbranch", {}).get("name", "main"),
            description=data.get("description"),
        )

    def list_repos(self, owner: str) -> List[RepoInfo]:
        """List all repositories in a Bitbucket workspace (with pagination)."""
        result = []
        next_url: Optional[str] = f"/repositories/{owner}"

        while next_url:
            try:
                data = self._get(next_url)
            except ValueError as exc:
                raise ValueError(
                    f"Cannot list repositories for '{owner}': {exc}"
                ) from exc

            for item in data.get("values", []):
                clone_url = ""
                ssh_url = ""
                for link in item.get("links", {}).get("clone", []):
                    if link["name"] == "https":
                        clone_url = link["href"]
                    elif link["name"] == "ssh":
                        ssh_url = link["href"]
                mainbranch = item.get("mainbranch") or {}
                result.append(RepoInfo(
                    name=item["name"],
                    full_name=item["full_name"],
                    clone_url=clone_url,
                    ssh_url=ssh_url,
                    private=item.get("is_private", True),
                    default_branch=mainbranch.get("name", "main"),
                    description=item.get("description"),
                ))

            raw_next = data.get("next")
            if raw_next:
                # Store only the path+query portion to keep _get() happy
                next_url = raw_next.replace(self._api_base, "")
            else:
                next_url = None

        return sorted(result, key=lambda r: r.name.lower())

    def get_authenticated_clone_url(self, repo: RepoInfo) -> str:
        """Embed username:app_password into the HTTPS clone URL."""
        parsed = urlparse(repo.clone_url)
        netloc = f"{self.creds.username}:{self.creds.password}@{parsed.hostname}"
        return parsed._replace(netloc=netloc).geturl()
