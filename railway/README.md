# Railway LLM-CLI Agent Box

Deploy hermes-agent on Railway as a **subscription-only** Claude agent box: a
simple web login where each teammate submits tasks, and behind the scenes Claude
Code runs on the box under **their own Claude Pro/Max subscription** — no
pay-per-token API, ever. Design rationale and the full backlog live in
[`.plans/railway-llm-cli-plugin.md`](../.plans/railway-llm-cli-plugin.md).

> **No-API guardrail.** The box refuses to start if `ANTHROPIC_API_KEY` /
> `OPENAI_API_KEY` is present (it would silently route Claude Code to paid API
> billing). Use `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` instead.

## What's here

| Path | Purpose |
|---|---|
| `Dockerfile.railway` | Slim image: hermes + Claude Code CLI, subscription-only |
| `railway.json` | Railway build/deploy (healthcheck, restart, volume) |
| `entrypoint.sh` | No-API guardrail, volume bootstrap, binds `/health` on `$PORT` |
| `.env.railway.example` | Every env var documented |
| `agentbox/` | Per-user encrypted token store + usage tracking (Epic B/C) |
| `bin/claude-as-user` | Run Claude Code under a teammate's own subscription |
| `config/mcp_servers.example.yaml` | Wire the gbrain shared brain over MCP (Epic D) |
| `openwebui.md` | Web front door (email/password login) |
| `gbrain.md` | Postgres (pgvector) + gbrain shared team brain |
| `openclaw-migration.md`, `RUNBOOK.md` | Migration + operator runbook |
| `tests/` | `python -m unittest railway.tests.test_agentbox` |

## Deploy order (maps to the implementation plan)

### Step 1 — Agent box (Phase 0)
1. New Railway service from this repo; it auto-detects `railway/railway.json`
   (or set the config path to `railway/railway.json`).
2. Add a **volume** mounted at `/opt/data` (`HERMES_HOME`).
3. Set service variables (see `.env.railway.example`): `API_SERVER_KEY`,
   `CLAUDE_CODE_OAUTH_TOKEN` (operator token from `claude setup-token`).
4. Deploy. **Verify:**
   - `GET https://<svc>/health` → 200
   - `curl -s https://<svc>/v1/chat/completions -H "Authorization: Bearer $API_SERVER_KEY"
     -H 'Content-Type: application/json' -d '{"model":"hermes-agent","messages":[{"role":"user","content":"have claude code print hello"}]}'`
     → real output; Anthropic console shows **zero** API spend.
   - Set a dummy `ANTHROPIC_API_KEY` and redeploy → the box **refuses to start**
     (guardrail working). Remove it.

### Step 2 — Web front door + login (Phase 1)
Follow [`openwebui.md`](./openwebui.md). Open WebUI is a second Railway service
with **email/password accounts, SSO off**, pointed at the box's `/v1`. Usage
tracking (who/when/where + per-task) is recorded by `agentbox.tracking`.

### Step 3 — Database + gbrain shared brain (Phase 1, day-one)
Follow [`gbrain.md`](./gbrain.md): add Railway's one-click **pgvector Postgres**,
reference `DATABASE_URL` into the box (this also moves the per-user token store
and usage log into Postgres automatically), deploy **gbrain** on the same DB, and
register it over MCP using `config/mcp_servers.example.yaml`.

### Step 4 — Personal agents on per-user tokens (Phase 2)
The `agentbox` package + `bin/claude-as-user` implement this. Each teammate
stores their own token:

```bash
# inside the box (or via an admin command), no-validate optional:
echo "$THEIR_SETUP_TOKEN" | python -m railway.agentbox.cli set-token alice --stdin
```

**Integration hook (the one wiring point):** the gateway already runs each
teammate in their own session with their account id. To make delegated coding
run on *their* subscription, point the `claude-code` skill at `claude-as-user`
instead of bare `claude`, passing the session's user id (e.g. export
`AGENTBOX_USER_ID=<account>` for that session, or call
`claude-as-user <account> ...`). `claude-as-user` looks up the encrypted token,
strips billing keys, injects `CLAUDE_CODE_OAUTH_TOKEN`, records the task, and
execs `claude`. Everything except this one redirect is already built and tested.

### Step 5 — Overnight prep + OpenClaw (Phase 3)
See [`cron/overnight-prep.example.md`](./cron/overnight-prep.example.md) and
[`openclaw-migration.md`](./openclaw-migration.md).

### Step 6 — Team rollout + hardening (Phase 4)
Add more accounts (no code change). Operate via [`RUNBOOK.md`](./RUNBOOK.md).

## Running the tests

```bash
python -m unittest railway.tests.test_agentbox -v
```

The base image's system `cryptography` may be too old; the Dockerfile pins
`cryptography>=43`. Locally, `pip install 'cryptography>=43'` if Fernet import
fails.

## Operator SSH

Railway provides a shell into the running container ("remote in and fix it").
SSH is also a first-class hermes terminal backend if you later want the box to
reach other machines.
