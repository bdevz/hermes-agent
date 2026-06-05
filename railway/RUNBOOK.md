# Operator Runbook (Epic F2)

Break-glass operations for the Railway agent box. Most fixes are done by SSHing
into the Railway shell — no redeploy needed.

## Quick health

```bash
curl -s https://<box>/health                 # expect 200
curl -s https://<box>/v1/models -H "Authorization: Bearer $API_SERVER_KEY"
claude --version                              # CLI present in the box
```

## Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| Box won't start, logs "model-billing API key detected" | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` set | Remove it from service variables (subscription-only box) |
| Box starts but Claude won't run for a user | no token stored for that user | `python -m railway.agentbox.cli has-token <user>`; have them re-paste `setup-token` |
| "Rate limit / overloaded" mid-task | that user's Claude plan throttled | Wait/back off; confirm they're on **Max**; spread heavy work out |
| A user's token stopped working | `setup-token` expired/revoked (1-yr) | `set-token` again with a fresh token; `revoke` the old |
| Sessions/skills lost after redeploy | volume not mounted at `/opt/data` | Attach a Railway volume at `HERMES_HOME` |
| gbrain `search`/`capture` failing | gbrain service down or MCP URL/token wrong | Check gbrain service + `GBRAIN_MCP_URL`/`GBRAIN_MCP_TOKEN` |

## Rate-limit handling (F2)

Per-user throttling should surface as a clear "throttled, retry later" state
with backoff rather than a raw error. When a teammate reports being stuck:

1. Confirm it's their own subscription limit (each user is isolated).
2. Verify their plan tier (Max recommended for unattended/overnight load).
3. Reschedule heavy cron jobs to off-peak if several land at once.

## Token & secret hygiene

- Tokens are encrypted at rest (`USER_CRED_ENC_KEY`, Fernet). **Back up that key
  separately** — losing it makes stored tokens unrecoverable (users just
  re-paste).
- Usage records never contain tokens/passwords (`agentbox.tracking` scrubs them).
- Never set a model-billing key on this service.

## Rotating the encryption key

1. Have users re-`set-token` after rotating `USER_CRED_ENC_KEY`, **or**
2. decrypt-then-reencrypt offline with both keys. Simplest is re-paste (tokens
   are cheap to regenerate via `claude setup-token`).

## Adding a teammate (F1 — no redeploy, no code change)

1. Create their Open WebUI account (email + set password).
2. They paste their own `setup-token` once.
3. Done — they work exactly like the PoC users.
