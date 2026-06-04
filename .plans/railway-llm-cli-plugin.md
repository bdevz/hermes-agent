# Railway LLM-CLI Plugin: Team Agents on a Box

> **Status:** Design / RFC (no code yet)
> **Author:** Hermes Agent team
> **One-line:** Deploy hermes-agent on Railway as a self-service "agent box" that
> wraps Claude Code, Codex, OpenCode, and OpenClaw behind a web interface, so
> every teammate gets a personal agent they can tag — and operators can SSH in
> to fix things behind the scenes.

---

## Motivation

The team wants a single, low-maintenance machine where:

1. You **drop in a token and Claude (or Codex, or another CLI) just runs** — with
   all the skills already wired up. No per-developer environment troubleshooting.
2. Tasks come in through a **simple web interface**; behind the scenes a coding-agent
   CLI executes on the box and streams output back.
3. **Every team member has their own personal agent** they can tag and hand
   prep/leg work to overnight, so the team walks in to finished work in the morning.
4. When something breaks, an operator can **remote-SSH into the box** and fix it
   without redeploying or bothering the team.

The important realization: **almost none of this needs to be built from scratch.**
`hermes-agent` already ships the hard parts. This plugin is mostly an
*integration + deployment* effort — packaging existing capabilities into a
Railway-deployable box with a clean web front door and per-user provisioning.

---

## What already exists (and maps directly to the vision)

| Vision element | Existing capability in this repo | Reference |
|---|---|---|
| Claude Code / Codex / OpenCode run on the box | Delegation skills that drive each CLI via the terminal backend (PTY, background mode, polling, mid-run input) | `skills/autonomous-ai-agents/{claude-code,codex,opencode}/SKILL.md` |
| "Task in → output back" web interface | OpenAI-compatible HTTP server (`/v1/chat/completions`, `/v1/responses`, `/v1/models`, `/health`) with Bearer-token auth and SSE streaming | `gateway/platforms/api_server.py` |
| Per-team-member agents you can @tag | Messaging gateways with per-user sessions (Discord, Slack, Telegram, Matrix, Mattermost, …) | `gateway/platforms/*.py` |
| "Armi's agent" / OpenClaw | First-class OpenClaw migration: `hermes claw migrate` imports `~/.openclaw` config/skills | `hermes_cli/claw.py` |
| Run anywhere, not the laptop | Six terminal backends: local, Docker, SSH, Daytona, Singularity, Modal | `README.md`, `environments/` |
| Skills come pre-wired | Skill system + `agentskills.io` standard; `hermes setup` wizard | `skills/`, `hermes_cli/setup.py` |
| Remote SSH to fix issues | Railway provides SSH into the running container; SSH is also a native terminal backend | Railway platform |

> **Clarification captured during scoping:** "Armi's agent" / "OpenClaude" refers to
> **OpenClaw**. It is handled by the existing `hermes claw migrate` path and is treated
> in this design as one of the wrapped agents, not a new integration.

### The actual gap

What is *not* yet in the repo, and is the real work of this plugin:

1. **A Railway deployment target** — no `railway.json`, no Railway-tuned image, no
   persistent-volume wiring for `HERMES_HOME`. The current `Dockerfile` is a heavy
   "everything" image (Playwright, WhatsApp bridge, ffmpeg) that is overkill for an
   agent box and slow to cold-start on Railway.
2. **The coding-agent CLIs baked into the image** — `@anthropic-ai/claude-code`,
   `@openai/codex`, `opencode` are assumed installed by the skills but are not in the
   image.
3. **A bundled web surface** — the API server exists, but nothing ships a ready-to-use
   UI. Decision: **bundle Open WebUI** pointed at the `/v1` endpoint (battle-tested,
   includes auth + multi-user, zero custom UI code).
4. **Per-user token / provisioning model** — "drop in a token and Claude runs" needs a
   defined story for where each user's `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` lives and
   how it is scoped to that user's agent.

---

## Architecture

```
                          Railway project
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │   ┌───────────────┐         ┌──────────────────────────────────────┐  │
  │   │  Open WebUI   │  /v1    │            hermes-agent              │  │
  │   │  (web front   │ ───────►│              gateway                 │  │
  │   │   door, auth, │  SSE    │   ┌────────────────────────────────┐ │  │
  │   │   per-user)   │ ◄───────│   │ api_server.py (OpenAI-compat)  │ │  │
  │   └───────────────┘         │   └────────────────────────────────┘ │  │
  │          ▲                  │   ┌────────────────────────────────┐ │  │
  │          │                  │   │ Discord / Slack gateway (@tag) │ │  │
  │   teammates' browsers       │   └────────────────────────────────┘ │  │
  │   + Discord/Slack tags      │              │ delegates via          │  │
  │                             │              ▼ terminal backend       │  │
  │                             │   ┌────────────────────────────────┐ │  │
  │                             │   │  claude  │  codex  │ opencode   │ │  │
  │                             │   │  (CLIs baked into the image)    │ │  │
  │                             │   └────────────────────────────────┘ │  │
  │                             └──────────────────────────────────────┘  │
  │                                          │                             │
  │                              Railway volume → HERMES_HOME (/opt/data)  │
  └──────────────────────────────────────────────────────────────────────┘
            ▲
            │  operator SSH (Railway shell) → fix/debug without redeploy
```

**Request flow for "give a task, get output":**

1. Teammate opens Open WebUI, picks the `hermes-agent` model, types a task.
2. Open WebUI calls `POST /v1/chat/completions` with `Authorization: Bearer <key>`.
3. `api_server.py` builds a session and runs the agent loop.
4. The agent picks the right delegation skill (`claude-code` / `codex` / `opencode`)
   and runs the CLI on the box via the terminal backend (`pty=true`, `background=true`
   for long jobs), polling for progress.
5. Streamed output flows back over SSE to Open WebUI.

**The "@tag your own agent" flow** reuses the messaging gateways — each teammate's
user ID maps to its own persistent session, so `@hermes do X` in Discord/Slack is
already a personal agent with its own memory.

---

## Provisioning model: "drop a token, Claude runs"

Three options, in increasing isolation. Recommend starting with **B**.

- **A — Shared box, shared keys.** One `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in
  Railway env vars; all users share the same agent identity. Simplest; no per-user
  cost attribution; fine for a small trusted team. *(MVP smoke-test only.)*
- **B — Shared box, per-user keys + per-user sessions (recommended).** Open WebUI
  accounts gate access; each user's API keys are stored against their session (via the
  gateway's per-user session store). One Railway service, clean separation of memory
  and cost per teammate, one box to operate.
- **C — One service per teammate.** Each person gets their own Railway service from the
  same image, with their own env/volume. Maximum isolation; higher cost and ops
  surface. Reserve for when B's blast radius becomes a concern.

**Token entry UX** ("drop in a token and Claude runs"): a teammate pastes their key
once; the box validates it (`claude` / `codex` auth check), persists it to their
session, and from then on their tasks run under their own key with all skills enabled.

---

## Deployment specifics (the real new work)

1. **`railway.json`** — build from a slim Dockerfile, healthcheck on `/health`, restart
   policy, and a volume mount at `HERMES_HOME` (`/opt/data`) so sessions/memory/skills
   survive redeploys.
2. **`Dockerfile.railway`** (new, slim) — Debian + python3 + nodejs, hermes installed
   with a *minimal* extras set (gateway + api_server), **plus** the coding-agent CLIs:
   `npm i -g @anthropic-ai/claude-code @openai/codex` and `opencode`. Skip Playwright /
   WhatsApp bridge / ffmpeg unless a teammate actually needs them — keeps cold starts
   fast.
3. **Open WebUI** — a second Railway service (or sidecar) configured with
   `OPENAI_API_BASE_URL` → the hermes service's `/v1` and `OPENAI_API_KEY` →
   `API_SERVER_KEY`. Gives auth + multi-user accounts for free.
4. **Env wiring** — `API_SERVER_ENABLED=true`, `API_SERVER_KEY`, `HERMES_HOME=/opt/data`,
   plus provider keys per the chosen provisioning model. Document the full set in a
   deploy guide derived from `.env.example`.
5. **Operator SSH** — document the Railway shell as the "remote in and fix it" path;
   note that SSH is also a first-class terminal backend if we later want the box to
   reach *other* machines.

---

## Phased rollout

- **Phase 0 — Smoke test (Option A).** Slim `Dockerfile.railway` + `railway.json`, CLIs
  baked in, shared key, API server on. Verify `claude`/`codex` run on the box and stream
  back through `/v1`. *Exit:* a task typed into `curl` (or Open WebUI) produces real
  Claude Code output.
- **Phase 1 — Web front door.** Bundle Open WebUI as a Railway service pointed at `/v1`,
  with accounts enabled. *Exit:* a teammate logs into a URL, types a task, watches it run.
- **Phase 2 — Personal agents (Option B).** Per-user sessions + per-user keys; enable the
  Discord/Slack gateway so `@tag` works alongside the web UI. *Exit:* two teammates run
  independent tasks with separate memory/cost under one box.
- **Phase 3 — OpenClaw + overnight prep.** Wire `hermes claw migrate` for users coming
  from OpenClaw; use the built-in cron scheduler for unattended overnight prep jobs that
  deliver results to each teammate's channel by morning.
- **Phase 4 — Hardening.** Per-user cost caps, secret handling review, log/redaction
  pass, and an operator runbook for the SSH-in workflow.

---

## Open questions

1. **Provisioning model** — confirm we start at Option B (shared box, per-user keys).
2. **Auth source of truth** — Open WebUI accounts, or an existing team SSO we should
   front it with?
3. **Cost controls** — do we need per-user spend caps in Phase 2, or defer to Phase 4?
4. **Which CLIs in v1** — Claude Code + Codex confirmed; include OpenCode and the
   OpenClaw path in the first image, or add later?
5. **Single box vs. per-teammate service** — how many people, and is shared-box blast
   radius acceptable to start?

---

## Why this is low-maintenance (the original goal)

- The box runs **one image** with the CLIs and skills baked in — no per-developer setup.
- **Open WebUI** handles accounts/UI so we maintain zero custom frontend.
- **Persistent volume** means redeploys don't wipe memory or skills.
- **SSH-in** gives operators a break-glass path without touching the team's workflow.
- Everything sits on **existing hermes-agent infrastructure**, so we inherit its
  sessions, skills, cron, and multi-platform gateways instead of reinventing them.
