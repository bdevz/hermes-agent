# Railway LLM-CLI Plugin: Team Agents on a Box

> **Status:** Design / RFC (no code yet)
> **Author:** Hermes Agent team
> **One-line:** Deploy hermes-agent on Railway as a self-service "agent box" that wraps
> **Claude Code** (v1 spine; Codex/OpenCode/OpenClaw architecturally supported, deferred)
> behind a web interface, so every teammate gets a personal agent they can tag — and
> operators can SSH in to fix things behind the scenes.
> **Runs entirely on Claude Pro/Max subscriptions — no pay-per-token API.**

---

## Motivation

The team wants a single, low-maintenance machine where:

1. You **drop in a Claude subscription token and Claude just runs** — with all the skills
   already wired up. No per-developer environment troubleshooting, no API billing.
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
2. **The coding-agent CLI baked into the image** — `@anthropic-ai/claude-code` is the
   v1 spine and must be in the image (it's assumed installed by the skill but isn't).
   Codex / OpenCode are deferred (also subscription-only when added — never API).
3. **A bundled web surface** — the local OpenAI-compatible HTTP server exists, but
   nothing ships a ready-to-use UI. Decision: **bundle Open WebUI** pointed at the `/v1`
   endpoint (battle-tested, includes auth + multi-user, zero custom UI code).
4. **Per-user subscription-token provisioning** — "drop in a token and Claude runs" needs
   a defined story for where each teammate's Claude **subscription** credential
   (`CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`) lives and how it's scoped to that
   teammate's agent. No model-billing API keys anywhere.

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

**Goal: no model-billing API anywhere. Everything runs on Claude subscriptions
(Pro/Max).** This is fully supported — at *both* layers of the stack — and the repo
already wires the Claude subscription paths.

> **Not to be confused:** the bundled web front door speaks the *OpenAI-compatible HTTP
> wire format* (`/v1/...`) so Open WebUI can connect. That is a local, free protocol —
> it is **not** the pay-per-token model API and involves no billing.

### Layer 1 — the delegated coding CLI (the heavy lifting)

| CLI | Subscription auth (no API) | Headless persistence |
|---|---|---|
| **Claude Code** (v1 spine) | `claude setup-token` → a **one-year OAuth token** set as `CLAUDE_CODE_OAUTH_TOKEN`. Authenticates against Pro/Max, **no per-token charge**, **no browser on the box**. Requires Pro/Max/Team/Enterprise. | env var (no browser flow needed) |

> ⚠️ **`ANTHROPIC_API_KEY` footgun.** If that env var is set *anywhere* on the box,
> Claude Code ignores the subscription and **bills the API.** The Railway env must keep
> it **unset** and use `CLAUDE_CODE_OAUTH_TOKEN` instead.

*(Codex / OpenCode are deferred. If/when added they'll use their own subscription
sign-in — Codex via "Sign in with ChatGPT", persisted on the volume — never API.)*

### Layer 2 — the hermes orchestrator brain

Also runs on the **Claude subscription**, no API key: `hermes login --provider anthropic`
uses the Claude `setup-token` credential store directly (`hermes_cli/main.py:2292`), so
the thing the web UI talks to is Claude too — keeping the stack all-Claude per the
decision. *Note:* the brain shares the same Claude rate-limit pool as the coding work, so
if brain chatter starts competing with Claude Code under load, the non-API relief valve
is to point only the brain at a separate Nous Portal subscription (still OAuth, still no
pay-per-token API). Defer that until rate limits actually bite.

### The catch that drives the design: one subscription = one person

Subscriptions are for **individual interactive use**. Funneling the whole team through
**one** person's plan is against ToS **and** throttles hard — rule of thumb: **1–3
agents** is comfortable on **Max**, but **5+ agents overnight hit rate limits within
hours**; **Pro ($20)** throttles far sooner than **Max ($100/$200)**.

**This makes "personal agent per teammate" the *correct* architecture, not a luxury:**
each teammate brings their **own** Claude Pro/Max and pastes their **own** `setup-token`.
That is ToS-clean (everyone on their own sub) and spreads rate limits across N accounts
instead of melting one. For unattended overnight team-scale work, plan on **Max**, not
Pro.

### Scope decision: build multi-user, prove it with 2–3

The harness is **multi-user from day one** (Option B below). We **PoC with 2–3
teammates'** subscriptions, then open it to the wider team without a refactor. We are
*not* building a single-person box — designing per-user sessions/tokens now is the
foundation that makes the team rollout a config change, not a rewrite. The PoC stays
ToS-clean because each of the 2–3 people is on their **own** subscription.

## Provisioning model: "drop a token, Claude runs"

**BYO-subscription, per user.** Build **B** as the foundation.

- **A — Shared box, one operator's token.** Single `CLAUDE_CODE_OAUTH_TOKEN` in env.
  Used **only** as the Phase 0 pipe-test to prove the wiring — never a multi-person mode
  (ToS + throttling).
- **B — Shared box, per-user subscription tokens + per-user sessions (the build).**
  Open WebUI accounts gate access; each teammate pastes their **own** `setup-token` once,
  stored against their session/volume. One service to operate, clean per-person
  isolation, rate limits spread across everyone's own plan. Scales from the 2–3 PoC to
  the whole team by just adding accounts.
- **C — One service per teammate.** Each person gets their own Railway service from the
  same image with their own env/volume. Maximum isolation; highest ops surface. Reserve
  for if/when B's shared-box blast radius becomes a concern at full team scale.

**Token entry UX** ("drop in a token and Claude runs") = a teammate pastes their own
`claude setup-token` once; the box validates it (`claude` auth check), persists it to
their session/volume, and from then on **their** tasks run under **their** Claude
subscription with all skills enabled — zero API billing.

---

## Deployment specifics (the real new work)

1. **`railway.json`** — build from a slim Dockerfile, healthcheck on `/health`, restart
   policy, and a volume mount at `HERMES_HOME` (`/opt/data`) so sessions/memory/skills
   survive redeploys.
2. **`Dockerfile.railway`** (new, slim) — Debian + python3 + nodejs, hermes installed
   with a *minimal* extras set (gateway + the local OpenAI-compatible server), **plus**
   the v1 coding CLI: `npm i -g @anthropic-ai/claude-code`. Skip Playwright / WhatsApp
   bridge / ffmpeg unless a teammate actually needs them — keeps cold starts fast.
   (Codex / OpenCode added later, subscription-only.)
3. **Open WebUI** — a second Railway service (or sidecar). Its own config vars
   `OPENAI_API_BASE_URL` → the hermes service's `/v1` and `OPENAI_API_KEY` →
   `API_SERVER_KEY` (the *local* server's auth token — **not** a model-billing key).
   Gives auth + multi-user accounts for free.
4. **Env wiring** — `API_SERVER_ENABLED=true`, `API_SERVER_KEY`, `HERMES_HOME=/opt/data`,
   and **Claude subscription** auth: `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`),
   per teammate. **`ANTHROPIC_API_KEY` must be *unset*** so Claude Code uses the
   subscription, never the API. No model-billing keys in the env at all. Document the full
   set in a deploy guide derived from `.env.example`.
5. **Operator SSH** — document the Railway shell as the "remote in and fix it" path;
   note that SSH is also a first-class terminal backend if we later want the box to
   reach *other* machines.

---

## Phased rollout

- **Phase 0 — Pipe test (Option A, single token).** Slim `Dockerfile.railway` +
  `railway.json`, Claude Code baked in, **one operator's `CLAUDE_CODE_OAUTH_TOKEN`**
  (subscription, no API key), local server on. Verify `claude` runs on the box on the
  subscription and streams back through `/v1`. *Exit:* a task via `curl` produces real
  Claude Code output with **no API charge**. (Single token here only proves wiring.)
- **Phase 1 — Web front door.** Bundle Open WebUI as a Railway service pointed at `/v1`,
  with accounts enabled. *Exit:* a teammate logs into a URL, types a task, watches it run.
- **Phase 2 — Multi-user PoC (Option B, 2–3 people).** Per-user sessions + per-user
  `setup-token`s; enable the Discord/Slack gateway so `@tag` works alongside the web UI.
  *Exit:* 2–3 teammates run independent tasks with separate memory and their own
  subscription rate-limit budgets under one box.
- **Phase 3 — OpenClaw + overnight prep.** Wire `hermes claw migrate` for users coming
  from OpenClaw; use the built-in cron scheduler for unattended overnight prep jobs that
  deliver results to each teammate's channel by morning.
- **Phase 4 — Open to the team + hardening.** Add the rest of the team as accounts (no
  refactor — B already supports it), per-user rate-limit handling, secret handling review,
  log/redaction pass, and an operator runbook for the SSH-in workflow.

---

### Decided

- ✅ **No model-billing API anywhere** — all-Claude subscription, both layers.
- ✅ **Provisioning** — Option B, multi-user from day one; PoC with 2–3 own-subscription
  teammates, then open to the team.
- ✅ **v1 CLI** — Claude Code only is the spine; Codex / OpenCode / OpenClaw deferred
  (subscription-only when added).
- ✅ **Topology** — single shared box (B); per-teammate services (C) only if blast radius
  bites at full scale.

### Still open

1. **Auth source of truth** — Open WebUI accounts, or front it with an existing team SSO?
2. **Brain rate-limit pressure** — start the orchestrator on Claude (all-Claude, simplest)
   and only split it onto a separate Nous subscription if brain chatter starts starving
   Claude Code under load? (Recommended: yes, start all-Claude, revisit if it bites.)
3. **Plan tier** — are the 2–3 PoC teammates on **Max**? Pro will throttle unattended
   overnight work much sooner.

---

## Why this is low-maintenance (the original goal)

- The box runs **one image** with the CLIs and skills baked in — no per-developer setup.
- **Open WebUI** handles accounts/UI so we maintain zero custom frontend.
- **Persistent volume** means redeploys don't wipe memory or skills.
- **SSH-in** gives operators a break-glass path without touching the team's workflow.
- Everything sits on **existing hermes-agent infrastructure**, so we inherit its
  sessions, skills, cron, and multi-platform gateways instead of reinventing them.
- **No API billing** — runs entirely on teammates' existing Claude Pro/Max subscriptions
  via `setup-token`, so cost is the flat subscription fee, nothing per-token.
