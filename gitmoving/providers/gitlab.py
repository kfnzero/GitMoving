"""GitLab provider adapter using python-gitlab."""

from typing import Optional
from urllib.parse import urlparse

import gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabGetError, GitlabCreateError

from ..auth.base import Credentials
from .base import BaseProvider, RepoInfo


class GitLabProvider(BaseProvider):
    PROVIDER_NAME = "gitlab"

    def __init__(self, creds: Credentials):
        super().__init__(creds)
        base_url = creds.base_url or "https://gitlab.com"
        self._client = gitlab.Gitlab(url=base_url, private_token=creds.token)

    def validate_credentials(self) -> str:
        try:
            self._client.auth()
            return self._client.user.username
        except GitlabAuthenticationError as exc:
            raise RuntimeError(f"GitLab authentication failed: {exc}") from exc

    def get_repo(self, owner: str, repo_name: str) -> RepoInfo:
        path = f"{owner}/{repo_name}"
        try:
            project = self._client.projects.get(path)
        except GitlabGetError as exc:
            raise ValueError(
                f"Repository '{path}' not found or not accessible: {exc}"
            ) from exc

        return RepoInfo(
            name=project.name,
            full_name=project.path_with_namespace,
            clone_url=project.http_url_to_repo,
            ssh_url=project.ssh_url_to_repo,
            private=project.visibility == "private",
            default_branch=project.default_branch or "main",
            description=project.description,
            topics=project.topics or [],
        )

    def create_repo(
        self,
        name: str,
        owner: Optional[str] = None,
        description: Optional[str] = None,
        private: bool = True,
    ) -> RepoInfo:
        visibility = "private" if private else "public"
        payload = {
            "name": name,
            "description": description or "",
            "visibility": visibility,
            "initialize_with_readme": False,
        }

        try:
            if owner:
                # Try to find the namespace (group or user)
                groups = self._client.groups.list(search=owner)
                group = next((g for g in groups if g.path == owner), None)
                if group:
                    payload["namespace_id"] = group.id
                else:
                    users = self._client.users.list(username=owner)
                    if users:
                        payload["namespace_id"] = users[0].id

            project = self._client.projects.create(payload)
        except GitlabCreateError as exc:
            raise RuntimeError(
                f"Failed to create GitLab repository '{name}': {exc}"
            ) from exc

        return RepoInfo(
            name=project.name,
            full_name=project.path_with_namespace,
            clone_url=project.http_url_to_repo,
            ssh_url=project.ssh_url_to_repo,
            private=project.visibility == "private",
            default_branch=project.default_branch or "main",
            description=project.description,
        )

    def get_authenticated_clone_url(self, repo: RepoInfo) -> str:
        """Return HTTPS URL with embedded PAT token (oauth2 username)."""
        parsed = urlparse(repo.clone_url)
        return parsed._replace(
            netloc=f"oauth2:{self.creds.token}@{parsed.hostname}"
        ).geturl()
