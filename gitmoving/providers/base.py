"""Abstract base class for Git hosting provider adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from ..auth.base import Credentials


@dataclass
class RepoInfo:
    """Normalized repository metadata across all providers."""
    name: str
    full_name: str          # e.g. "owner/repo"
    clone_url: str          # HTTPS clone URL (with embedded token when available)
    ssh_url: str
    private: bool
    default_branch: str
    description: Optional[str] = None
    topics: list = field(default_factory=list)


class BaseProvider(ABC):
    """
    Abstract adapter for a Git hosting platform.

    Responsibilities:
    - Authenticate and validate credentials.
    - Fetch metadata for existing repositories.
    - Create new repositories on the platform.
    - Return authenticated clone URLs for git operations.
    """

    PROVIDER_NAME: str = ""

    def __init__(self, creds: Credentials):
        self.creds = creds
        self._client = None

    @abstractmethod
    def validate_credentials(self) -> str:
        """
        Verify that the stored credentials are valid.

        Returns:
            The authenticated username/login on success.

        Raises:
            RuntimeError: If authentication fails.
        """

    @abstractmethod
    def get_repo(self, owner: str, repo_name: str) -> RepoInfo:
        """
        Fetch metadata for an existing repository.

        Args:
            owner: Organisation or user that owns the repository.
            repo_name: Repository name (without owner prefix).

        Returns:
            A populated RepoInfo instance.

        Raises:
            ValueError: If the repository does not exist or is not accessible.
        """

    @abstractmethod
    def create_repo(
        self,
        name: str,
        owner: Optional[str] = None,
        description: Optional[str] = None,
        private: bool = True,
    ) -> RepoInfo:
        """
        Create a new repository on the platform.

        Args:
            name: Repository name.
            owner: Organisation or namespace to create under (None = personal account).
            description: Optional description string.
            private: Whether to create as a private repository (default True).

        Returns:
            RepoInfo for the newly created repository.
        """

    @abstractmethod
    def get_authenticated_clone_url(self, repo: RepoInfo) -> str:
        """
        Return an HTTPS clone URL with credentials embedded so that git
        operations do not require a separate credential prompt.

        Example:
            https://<token>@github.com/owner/repo.git
        """

    @abstractmethod
    def list_repos(self, owner: str) -> List[RepoInfo]:
        """
        List all repositories accessible under the given owner/org/namespace.

        Args:
            owner: Username or organisation/group name.

        Returns:
            List of RepoInfo objects, sorted by name.

        Raises:
            ValueError: If the owner does not exist or is not accessible.
        """

    def repo_exists(self, owner: str, repo_name: str) -> bool:
        """Return True if the repository exists and is accessible."""
        try:
            self.get_repo(owner, repo_name)
            return True
        except ValueError:
            return False
