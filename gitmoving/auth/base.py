"""Base authentication classes and credential storage."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import keyring
import os


KEYRING_SERVICE = "gitmoving"


@dataclass
class Credentials:
    """Holds authentication credentials for a Git provider."""
    provider: str
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    base_url: Optional[str] = None  # For self-hosted GitLab / Bitbucket Server


class BaseAuth(ABC):
    """Abstract base class for provider authentication."""

    PROVIDER_NAME: str = ""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url

    @abstractmethod
    def authenticate_interactive(self) -> Credentials:
        """
        Prompt the user interactively for credentials and return them.
        This is called when no saved credentials are found.
        """

    def save_credentials(self, creds: Credentials, label: str = "default") -> None:
        """Persist credentials to the system keyring."""
        service = f"{KEYRING_SERVICE}/{self.PROVIDER_NAME}/{label}"
        if creds.token:
            keyring.set_password(service, "token", creds.token)
        if creds.username:
            keyring.set_password(service, "username", creds.username)
        if creds.password:
            keyring.set_password(service, "password", creds.password)
        if creds.base_url:
            keyring.set_password(service, "base_url", creds.base_url)

    def load_credentials(self, label: str = "default") -> Optional[Credentials]:
        """Load previously saved credentials from the system keyring."""
        service = f"{KEYRING_SERVICE}/{self.PROVIDER_NAME}/{label}"
        token = keyring.get_password(service, "token")
        username = keyring.get_password(service, "username")
        password = keyring.get_password(service, "password")
        base_url = keyring.get_password(service, "base_url") or self.base_url

        if not (token or (username and password)):
            return None

        return Credentials(
            provider=self.PROVIDER_NAME,
            token=token,
            username=username,
            password=password,
            base_url=base_url,
        )

    def clear_credentials(self, label: str = "default") -> None:
        """Remove saved credentials from the keyring."""
        service = f"{KEYRING_SERVICE}/{self.PROVIDER_NAME}/{label}"
        for key in ("token", "username", "password", "base_url"):
            try:
                keyring.delete_password(service, key)
            except keyring.errors.PasswordDeleteError:
                pass

    def get_or_prompt(self, label: str = "default", force_reauth: bool = False) -> Credentials:
        """
        Return saved credentials if available, otherwise prompt the user.

        Args:
            label: Namespace label (e.g. "source" / "destination").
            force_reauth: Always prompt even if credentials exist.
        """
        if not force_reauth:
            # Check environment variables first
            env_creds = self._load_from_env()
            if env_creds:
                return env_creds

            saved = self.load_credentials(label)
            if saved:
                return saved

        creds = self.authenticate_interactive()
        self.save_credentials(creds, label)
        return creds

    def _load_from_env(self) -> Optional[Credentials]:
        """Override in subclasses to support provider-specific env vars."""
        return None
