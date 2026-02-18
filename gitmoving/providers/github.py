"""GitHub provider adapter using PyGithub."""

from typing import List, Optional
from urllib.parse import urlparse

from github import Github, GithubException, Auth

from ..auth.base import Credentials
from .base import BaseProvider, RepoInfo


class GitHubProvider(BaseProvider):
    PROVIDER_NAME = "github"

    def __init__(self, creds: Credentials):
        super().__init__(creds)
        base_url = creds.base_url or "https://api.github.com"
        auth = Auth.Token(creds.token)

        if base_url == "https://api.github.com":
            self._client = Github(auth=auth)
        else:
            self._client = Github(base_url=base_url, auth=auth)

    def validate_credentials(self) -> str:
        try:
            user = self._client.get_user()
            return user.login
        except GithubException as exc:
            raise RuntimeError(
                f"GitHub authentication failed: {exc.data.get('message', str(exc))}"
            ) from exc

    def get_repo(self, owner: str, repo_name: str) -> RepoInfo:
        try:
            repo = self._client.get_repo(f"{owner}/{repo_name}")
        except GithubException as exc:
            raise ValueError(
                f"Repository '{owner}/{repo_name}' not found or not accessible: "
                f"{exc.data.get('message', str(exc))}"
            ) from exc

        return RepoInfo(
            name=repo.name,
            full_name=repo.full_name,
            clone_url=repo.clone_url,
            ssh_url=repo.ssh_url,
            private=repo.private,
            default_branch=repo.default_branch,
            description=repo.description,
            topics=repo.get_topics(),
        )

    def create_repo(
        self,
        name: str,
        owner: Optional[str] = None,
        description: Optional[str] = None,
        private: bool = True,
    ) -> RepoInfo:
        try:
            me = self._client.get_user()
            if owner and owner.lower() != me.login.lower():
                # Create under an organisation
                org = self._client.get_organization(owner)
                repo = org.create_repo(
                    name=name,
                    description=description or "",
                    private=private,
                    auto_init=False,
                )
            else:
                repo = me.create_repo(
                    name=name,
                    description=description or "",
                    private=private,
                    auto_init=False,
                )
        except GithubException as exc:
            raise RuntimeError(
                f"Failed to create GitHub repository '{name}': "
                f"{exc.data.get('message', str(exc))}"
            ) from exc

        return RepoInfo(
            name=repo.name,
            full_name=repo.full_name,
            clone_url=repo.clone_url,
            ssh_url=repo.ssh_url,
            private=repo.private,
            default_branch=repo.default_branch,
            description=repo.description,
        )

    def list_repos(self, owner: str) -> List[RepoInfo]:
        """List all repositories for a user or organisation."""
        try:
            me = self._client.get_user()
            if owner.lower() == me.login.lower():
                raw_repos = me.get_repos(type="all")
            else:
                org = self._client.get_organization(owner)
                raw_repos = org.get_repos(type="all")
        except GithubException as exc:
            raise ValueError(
                f"Cannot list repositories for '{owner}': "
                f"{exc.data.get('message', str(exc))}"
            ) from exc

        result = []
        for repo in raw_repos:
            result.append(RepoInfo(
                name=repo.name,
                full_name=repo.full_name,
                clone_url=repo.clone_url,
                ssh_url=repo.ssh_url,
                private=repo.private,
                default_branch=repo.default_branch or "main",
                description=repo.description,
            ))
        return sorted(result, key=lambda r: r.name.lower())

    def get_authenticated_clone_url(self, repo: RepoInfo) -> str:
        """Return HTTPS URL with embedded PAT token."""
        parsed = urlparse(repo.clone_url)
        return parsed._replace(
            netloc=f"{self.creds.token}@{parsed.hostname}"
        ).geturl()
