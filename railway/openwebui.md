# Web front door — Open WebUI (Epic B)

The web interface is **Open WebUI** as a second Railway service, pointed at the
agent box's local OpenAI-compatible endpoint. Zero custom UI code; it brings
email/password accounts and per-user activity for free.

> The box's `/v1` server speaks the **OpenAI wire format** so Open WebUI can
> connect. That is a free local protocol — **not** pay-per-token API billing.

## Deploy

1. New Railway service from image `ghcr.io/open-webui/open-webui:main`.
2. Add a volume at `/app/backend/data` (persists accounts).
3. Set variables:

   | Variable | Value | Why |
   |---|---|---|
   | `OPENAI_API_BASE_URL` | `https://<agent-box>/v1` | point at the box |
   | `OPENAI_API_KEY` | the box's `API_SERVER_KEY` | **local** auth token, not a billing key |
   | `ENABLE_LOGIN_FORM` | `true` | email/password login |
   | `ENABLE_OAUTH_SIGNUP` | `false` | **no SSO** |
   | `ENABLE_SIGNUP` | `false` | admin creates accounts |
   | `WEBUI_AUTH` | `true` | require login |

4. Deploy, open the URL, create the admin account, then add each teammate
   (B1: email + a set password).

## Login & task flow (B1/B3)

A teammate logs in, selects the `hermes-agent` model, types a task, and watches
Claude Code output stream back (SSE). Long tasks run in the background with
progress (the box uses `background=true` PTY sessions under the hood).

## Usage tracking (B2 — who / when / where)

Two layers, no secrets stored:

- **Open WebUI** records accounts and login/activity in its own DB.
- **Source IP / location:** Railway sits behind a proxy; capture the client IP
  from `X-Forwarded-For` at the edge and feed it to
  `agentbox.tracking.UsageTracker.record_login(user, ip, location)`.
- **Per-task attribution:** when a task is dispatched for a logged-in user, call
  `record_task(user, summary)`. `agentbox.tracking` scrubs any token/password
  fields defensively, so records never contain secrets.

Inspect:

```bash
python -m railway.agentbox.cli logins --limit 50
python -m railway.agentbox.cli tasks  --user alice
```

Aggregate dashboards (tasks/day per user) are intentionally **P2** — out of
scope for the PoC.
