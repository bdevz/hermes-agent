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

## Auth model: subscriptions, not API (the explicit goal)

**Goal: no pay-per-token API. Use Claude Pro/Max + Codex (ChatGPT) Pro + other Pro
subscriptions.** This is fully supported — at *both* layers of the stack — and the
repo already wires the non-API paths.

### Layer 1 — the delegated coding CLIs (the heavy lifting)

| CLI | Subscription auth (no API) | Headless persistence |
|---|---|---|
| **Claude Code** | `claude setup-token` → a **one-year OAuth token** set as `CLAUDE_CODE_OAUTH_TOKEN`. Authenticates against Pro/Max, **no per-token charge**, **no browser on the box**. Requires Pro/Max/Team/Enterprise. | env var (no browser flow needed) |
| **Codex CLI** | "Sign in with ChatGPT" → usage follows your Plus/Pro plan allowances. | persist `~/.codex/auth.json` on the volume |

> ⚠️ **`ANTHROPIC_API_KEY` footgun.** If that env var is set *anywhere* on the box,
> Claude Code ignores the subscription and **bills the API.** The Railway env must keep
> it **unset** and use `CLAUDE_CODE_OAUTH_TOKEN` instead.

### Layer 2 — the hermes orchestrator brain

Also subscription-capable, no API key required:
`hermes login --provider anthropic` (Claude `setup-token` credential store —
`hermes_cli/main.py:2292`), `--provider openai-codex`, or `--provider nous`. So the
thing the web UI talks to can *also* run off a subscription. (If keeping the orchestrator
maximally simple is preferred, the web UI can drive the coding CLIs more directly — but
the subscription-brain path means we don't have to.)

### The catch that drives the design: one subscription = one person

Subscriptions are for **individual interactive use**. Funneling the whole team through
**one** person's plan is against ToS **and** throttles hard — rule of thumb: **1–3
agents** is comfortable on **Max**, but **5+ agents overnight hit rate limits within
hours**; **Pro ($20)** throttles far sooner than **Max ($100/$200)**.

**This makes "personal agent per teammate" the *correct* architecture, not a luxury:**
each teammate brings their **own** Claude Pro/Max + Codex Pro and pastes their **own**
`setup-token`. That is ToS-clean (everyone on their own sub) and spreads rate limits
across N accounts instead of melting one. For unattended overnight team-scale work,
plan on **Max**, not Pro.

## Provisioning model: "drop a token, Claude runs"

Revised for **BYO-subscription** (was: per-user API keys). Recommend starting with **B**.

- **A — Shared box, one operator's subscription.** Single `CLAUDE_CODE_OAUTH_TOKEN` +
  Codex login in env. Simplest, but ToS-grey and throttles under team load.
  *(Smoke-test only — never the team default.)*
- **B — Shared box, per-user subscription tokens + per-user sessions (recommended).**
  Open WebUI accounts gate access; each teammate pastes their **own** `setup-token` /
  Codex login once, stored against their session. One service to operate, clean
  per-person isolation, rate limits spread across everyone's own plan.
- **C — One service per teammate.** Each person gets their own Railway service from the
  same image with their own env/volume. Maximum isolation; highest ops surface. Reserve
  for when B's blast radius is a concern.

**Token entry UX** ("drop in a token and Claude runs") = a teammate pastes their own
`claude setup-token` (and signs into Codex) once; the box validates it (`claude` /
`codex` auth check), persists it to their session/volume, and from then on **their**
tasks run under **their** subscription with all skills enabled — zero API billing.

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
   and **subscription** auth per the provisioning model: `CLAUDE_CODE_OAUTH_TOKEN` for
   Claude Code (from `claude setup-token`) and persisted `~/.codex/auth.json` for Codex.
   **Ensure `ANTHROPIC_API_KEY` is *unset*** so Claude Code uses the subscription, not the
   API. Document the full set in a deploy guide derived from `.env.example`.
5. **Operator SSH** — document the Railway shell as the "remote in and fix it" path;
   note that SSH is also a first-class terminal backend if we later want the box to
   reach *other* machines.

---

## Phased rollout

- **Phase 0 — Smoke test (Option A).** Slim `Dockerfile.railway` + `railway.json`, CLIs
  baked in, **one operator's `CLAUDE_CODE_OAUTH_TOKEN`** (subscription, no API key), API
  server on. Verify `claude`/`codex` run on the box on the subscription and stream back
  through `/v1`. *Exit:* a task typed into `curl` (or Open WebUI) produces real Claude
  Code output with **no API charge**.
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

1. **Provisioning model** — confirm we start at Option B (shared box, **per-user
   subscription tokens** — each teammate BYO Claude Pro/Max + Codex Pro). Phase 0 can use
   one operator's token to prove the pipe.
2. **Auth source of truth** — Open WebUI accounts, or an existing team SSO we should
   front it with?
3. **Rate-limit handling** — with subscriptions there is no per-token spend, but per-plan
   rate limits. Do we need queueing/backoff + Pro-vs-Max guidance per teammate in Phase 2,
   or defer to Phase 4? (Subscription throttling, not API cost, is the real constraint.)
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
- **No API billing** — runs entirely on teammates' existing Claude Pro/Max + Codex Pro
  subscriptions via `setup-token` / ChatGPT sign-in, so there's a flat, predictable cost.
