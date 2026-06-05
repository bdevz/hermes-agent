"""
agentbox CLI — manage per-user Claude tokens and inspect usage.

Usage:
    python -m railway.agentbox.cli set-token  <user_id> [--token T | --stdin] [--no-validate]
    python -m railway.agentbox.cli has-token  <user_id>
    python -m railway.agentbox.cli revoke     <user_id>
    python -m railway.agentbox.cli list-users
    python -m railway.agentbox.cli run        <user_id> -- <claude args...>
    python -m railway.agentbox.cli logins     [--limit N]
    python -m railway.agentbox.cli tasks      [--user U] [--limit N]
    python -m railway.agentbox.cli gen-key

`run` is the delegation entrypoint: it looks up the user's token and execs
`claude` with their subscription env (billing keys stripped), recording the task.
"""

from __future__ import annotations

import argparse
import os
import sys

from .credstore import CredentialStore, generate_enc_key
from .tokens import build_user_env, validate_token
from .tracking import UsageTracker


def _store() -> CredentialStore:
    return CredentialStore()


def cmd_gen_key(_args) -> int:
    print(generate_enc_key())
    return 0


def cmd_set_token(args) -> int:
    token = args.token
    if args.stdin or not token:
        token = sys.stdin.readline().strip()
    if not token:
        print("error: no token provided", file=sys.stderr)
        return 2
    if not args.no_validate:
        ok, msg = validate_token(token)
        if not ok:
            print(f"token validation failed: {msg}", file=sys.stderr)
            print("(use --no-validate to store without checking)", file=sys.stderr)
            return 1
        print(f"token validated: {msg}")
    _store().set_token(args.user_id, token)
    print(f"stored token for {args.user_id}")
    return 0


def cmd_has_token(args) -> int:
    has = _store().has_token(args.user_id)
    print("yes" if has else "no")
    return 0 if has else 1


def cmd_revoke(args) -> int:
    revoked = _store().revoke(args.user_id)
    print("revoked" if revoked else "no token to revoke")
    return 0 if revoked else 1


def cmd_list_users(_args) -> int:
    for uid in _store().list_users():
        print(uid)
    return 0


def cmd_run(args) -> int:
    token = _store().get_token(args.user_id)
    if not token:
        print(f"error: no token for {args.user_id}; run set-token first", file=sys.stderr)
        return 1
    env = build_user_env(token)
    claude_args = args.claude_args or []
    UsageTracker().record_task(
        args.user_id,
        summary=" ".join(claude_args)[:200] or "(interactive)",
    )
    os.execvpe("claude", ["claude", *claude_args], env)  # replace process
    return 0  # unreachable


def cmd_logins(args) -> int:
    for rec in UsageTracker().recent_logins(args.limit):
        print(rec)
    return 0


def cmd_tasks(args) -> int:
    tracker = UsageTracker()
    rows = tracker.for_user(args.user, args.limit) if args.user else tracker.recent_tasks(args.limit)
    for rec in rows:
        print(rec)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentbox", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("set-token", help="store a user's Claude subscription token")
    s.add_argument("user_id")
    s.add_argument("--token", help="token value (or use --stdin)")
    s.add_argument("--stdin", action="store_true", help="read token from stdin")
    s.add_argument("--no-validate", action="store_true", help="skip live validation")
    s.set_defaults(func=cmd_set_token)

    s = sub.add_parser("has-token", help="check if a user has a stored token")
    s.add_argument("user_id")
    s.set_defaults(func=cmd_has_token)

    s = sub.add_parser("revoke", help="delete a user's stored token")
    s.add_argument("user_id")
    s.set_defaults(func=cmd_revoke)

    s = sub.add_parser("list-users", help="list users with a stored token")
    s.set_defaults(func=cmd_list_users)

    s = sub.add_parser("run", help="run claude as a user (their subscription)")
    s.add_argument("user_id")
    s.add_argument("claude_args", nargs=argparse.REMAINDER,
                   help="args after -- are passed to claude")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("logins", help="recent login events")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_logins)

    s = sub.add_parser("tasks", help="recent task events")
    s.add_argument("--user", help="filter to one user")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_tasks)

    s = sub.add_parser("gen-key", help="generate a USER_CRED_ENC_KEY")
    s.set_defaults(func=cmd_gen_key)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
