"""
agentbox — Railway LLM-CLI agent box support library.

Self-contained, additive helpers for running hermes-agent on Railway as a
multi-user, subscription-only Claude agent box:

- ``credstore``  encrypted per-user Claude subscription-token store (Epic C1)
- ``tracking``   lightweight usage tracking: login + per-task (Epic B2)
- ``tokens``     validate a setup-token and build a per-user subprocess env
- ``backends``   pluggable storage (file by default, Postgres when DATABASE_URL set)

Nothing here mutates hermes internals; it is consumed by a thin integration
shim (see railway/README.md → "Step 4 integration"). This keeps the
multi-user/credential logic reviewable and unit-testable in isolation.
"""

from .backends import FileBackend, PostgresBackend, get_backend
from .credstore import CredentialStore, generate_enc_key
from .tracking import UsageTracker
from .tokens import build_user_env, strip_billing_keys, validate_token

__all__ = [
    "FileBackend",
    "PostgresBackend",
    "get_backend",
    "CredentialStore",
    "generate_enc_key",
    "UsageTracker",
    "build_user_env",
    "strip_billing_keys",
    "validate_token",
]
