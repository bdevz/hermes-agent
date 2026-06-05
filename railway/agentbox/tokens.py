"""
Token validation + per-user subprocess environment construction.

- :func:`strip_billing_keys` enforces the no-API guardrail at the delegation
  boundary (belt-and-suspenders with the entrypoint check).
- :func:`build_user_env` produces the environment a teammate's Claude Code
  subprocess should run with: their subscription token in, billing keys out.
- :func:`validate_token` does a best-effort live check that a setup-token works.
"""

from __future__ import annotations

import os
import subprocess
from typing import Dict, Mapping, Optional, Tuple

# Keys that would route Claude Code (or the orchestrator) to pay-per-token
# billing. They must never reach a delegated subprocess on this box.
BILLING_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_TOKEN")


def strip_billing_keys(env: Mapping[str, str]) -> Dict[str, str]:
    """Return a copy of ``env`` with all model-billing keys removed."""
    return {k: v for k, v in env.items() if k not in BILLING_KEYS}


def build_user_env(
    user_token: str,
    base_env: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """
    Build the environment for a per-user Claude Code subprocess.

    Starts from ``base_env`` (defaults to the current process env), strips every
    billing key, and injects the user's subscription token so the work bills to
    *their* Claude plan, not the API and not a shared account.
    """
    if not user_token or not user_token.strip():
        raise ValueError("user_token is required")
    env = strip_billing_keys(base_env if base_env is not None else os.environ)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = user_token.strip()
    return env


def validate_token(
    token: str,
    timeout: int = 60,
    claude_bin: str = "claude",
) -> Tuple[bool, str]:
    """
    Best-effort live validation of a Claude subscription ``setup-token``.

    Runs a tiny headless Claude Code prompt with the token injected (and billing
    keys stripped). Returns ``(ok, message)``. Network/CLI-dependent, so callers
    should treat failures as "could not verify" rather than hard errors.
    """
    if not token or not token.strip():
        return False, "empty token"
    env = build_user_env(token)
    try:
        proc = subprocess.run(
            [claude_bin, "-p", "Reply with the single word: ok"],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, f"{claude_bin} not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "validation timed out"
    if proc.returncode == 0:
        return True, "ok"
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, detail[-1] if detail else f"exit code {proc.returncode}"
