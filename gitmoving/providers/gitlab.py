"""GitLab provider adapter using python-gitlab."""

from typing import List, Optional
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

    def list_repos(self, owner: str) -> List[RepoInfo]:
        """List all projects in a group or for a user."""
        projects = []
        try:
            # Try as a group first
            group = self._client.groups.get(owner)
            raw = group.projects.list(all=True, include_subgroups=False)
            # group.projects returns GroupProject; fetch full Project for URLs
            for gp in raw:
                try:
                    p = self._client.projects.get(gp.id)
                    projects.append(p)
                except Exception:
                    pass
        except Exception:
            # Fall back to listing owned projects filtered by namespace
            try:
                raw = self._client.projects.list(owned=True, all=True)
                projects = [
                    p for p in raw
                    if p.namespace.get("path", "").lower() == owner.lower()
                ] or list(raw)
            except Exception as exc:
                raise ValueError(
                    f"Cannot list repositories for '{owner}': {exc}"
                ) from exc

        result = []
        for p in projects:
            result.append(RepoInfo(
                name=p.name,
                full_name=p.path_with_namespace,
                clone_url=p.http_url_to_repo,
                ssh_url=p.ssh_url_to_repo,
                private=p.visibility == "private",
                default_branch=getattr(p, "default_branch", None) or "main",
                description=getattr(p, "description", None),
                topics=getattr(p, "topics", []) or [],
            ))
        return sorted(result, key=lambda r: r.name.lower())

    def get_authenticated_clone_url(self, repo: RepoInfo) -> str:
        """Return HTTPS URL with embedded PAT token (oauth2 username)."""
        parsed = urlparse(repo.clone_url)
        return parsed._replace(
            netloc=f"oauth2:{self.creds.token}@{parsed.hostname}"
        ).geturl()
