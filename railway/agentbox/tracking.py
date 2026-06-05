"""
Lightweight usage tracking (Epic B2): who logged in, when, from where, and
which tasks ran under which account.

Deliberately minimal — the approved scope is login + per-task attribution, not
analytics dashboards (those are P2). Records carry NO secrets: tokens and
passwords must never be passed in here.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .backends import StorageBackend, get_backend

_LOGIN_STREAM = "usage_logins"
_TASK_STREAM = "usage_tasks"

# Defensive: never let a caller accidentally persist a secret.
_FORBIDDEN_KEYS = {"token", "password", "secret", "api_key", "oauth_token"}


def _sanitize(detail: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not detail:
        return {}
    return {k: v for k, v in detail.items() if k.lower() not in _FORBIDDEN_KEYS}


class UsageTracker:
    """Append-only login/task event recorder."""

    def __init__(self, backend: Optional[StorageBackend] = None):
        self._backend = backend or get_backend()

    def record_login(
        self,
        user_id: str,
        ip: Optional[str] = None,
        location: Optional[str] = None,
        success: bool = True,
    ) -> None:
        """Record a login attempt (who / when / where)."""
        self._backend.log_append(
            _LOGIN_STREAM,
            {
                "user_id": user_id,
                "ip": ip,
                "location": location,
                "success": success,
                "ts": time.time(),
            },
        )

    def record_task(
        self,
        user_id: str,
        summary: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Attribute a submitted task to a user (no secrets in ``detail``)."""
        self._backend.log_append(
            _TASK_STREAM,
            {
                "user_id": user_id,
                "summary": summary,
                "detail": _sanitize(detail),
                "ts": time.time(),
            },
        )

    def recent_logins(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._backend.log_read(_LOGIN_STREAM, limit)

    def recent_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._backend.log_read(_TASK_STREAM, limit)

    def for_user(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """All recent task events attributed to a single user."""
        return [
            r for r in self._backend.log_read(_TASK_STREAM, limit)
            if r.get("user_id") == user_id
        ]
