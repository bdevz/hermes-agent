"""
Encrypted per-user Claude subscription-token store (Epic C1).

Each teammate pastes their own ``claude setup-token`` once; it is encrypted at
rest (Fernet / AES-128-CBC + HMAC) and stored keyed by their account id. Tasks
then run under *their* subscription, isolating rate limits per person.

The encryption key comes from ``USER_CRED_ENC_KEY`` (a Fernet key). Generate one
with :func:`generate_enc_key`. Tokens are never logged or returned in listings —
only :meth:`get_token` decrypts, and only for the delegation path.
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

from cryptography.fernet import Fernet, InvalidToken

from .backends import StorageBackend, get_backend

_NAMESPACE = "user_credentials"


def generate_enc_key() -> str:
    """Return a fresh Fernet key suitable for USER_CRED_ENC_KEY."""
    return Fernet.generate_key().decode()


class CredentialStore:
    """Encrypted store mapping ``user_id -> Claude subscription token``."""

    def __init__(
        self,
        enc_key: Optional[str] = None,
        backend: Optional[StorageBackend] = None,
    ):
        key = enc_key or os.getenv("USER_CRED_ENC_KEY")
        if not key:
            raise ValueError(
                "USER_CRED_ENC_KEY is required to encrypt user tokens. "
                "Generate one with agentbox.generate_enc_key()."
            )
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "USER_CRED_ENC_KEY is not a valid Fernet key (urlsafe base64, 32 bytes). "
                "Generate one with agentbox.generate_enc_key()."
            ) from exc
        self._backend = backend or get_backend()

    def set_token(self, user_id: str, token: str) -> None:
        """Encrypt and store ``token`` for ``user_id`` (overwrites any existing)."""
        if not user_id:
            raise ValueError("user_id is required")
        if not token or not token.strip():
            raise ValueError("token is required")
        now = time.time()
        existing = self._backend.kv_get(_NAMESPACE, user_id)
        created = existing.get("created_at", now) if existing else now
        ciphertext = self._fernet.encrypt(token.strip().encode()).decode()
        self._backend.kv_set(
            _NAMESPACE,
            user_id,
            {"token": ciphertext, "created_at": created, "updated_at": now},
        )

    def get_token(self, user_id: str) -> Optional[str]:
        """Return the decrypted token for ``user_id``, or ``None`` if absent/corrupt."""
        record = self._backend.kv_get(_NAMESPACE, user_id)
        if not record or "token" not in record:
            return None
        try:
            return self._fernet.decrypt(record["token"].encode()).decode()
        except InvalidToken:
            # Wrong key or tampered ciphertext — treat as "no usable token"
            # rather than leaking a decryption error to callers.
            return None

    def has_token(self, user_id: str) -> bool:
        return self._backend.kv_get(_NAMESPACE, user_id) is not None

    def revoke(self, user_id: str) -> bool:
        """Delete a user's stored token. Returns True if one existed."""
        return self._backend.kv_delete(_NAMESPACE, user_id)

    def list_users(self) -> List[str]:
        """User ids that have a stored token (never returns tokens themselves)."""
        return self._backend.kv_keys(_NAMESPACE)
