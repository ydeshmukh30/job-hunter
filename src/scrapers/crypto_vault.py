"""Fernet-encrypted credential vault for platform passwords."""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet


class CryptoVault:
    """Lazy-decrypting credential store backed by config/credentials.enc."""

    def __init__(self, key: bytes) -> None:
        # Accept a raw Fernet key (32 url-safe base64 bytes) or the encoded bytes
        self._fernet = Fernet(key)
        self._cache: dict | None = None
        self._enc_path = Path("config/credentials.enc")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get(self, platform: str) -> dict:
        """Return the credential dict for *platform*.

        Raises:
            FileNotFoundError: if credentials.enc does not exist.
            KeyError: if *platform* is not in the decrypted data.
        """
        if self._cache is None:
            self._cache = self._load()
        return self._cache[platform]

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _load(self) -> dict:
        if not self._enc_path.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self._enc_path}. "
                "Run `python src/scrapers/encrypt_creds.py` to create it."
            )
        encrypted = self._enc_path.read_bytes()
        plaintext = self._fernet.decrypt(encrypted)
        return json.loads(plaintext.decode("utf-8"))
