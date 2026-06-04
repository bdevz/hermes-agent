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
5. **A modern shared database + team brain** — a managed Postgres (pgvector) as the durable
   backbone for users, usage tracking, and shared knowledge, plus an evaluation of
   **gbrain** as the MCP-native synthesized team-memory layer on top of it (Epic D).

---

## Architecture

```
                          Railway project
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │   ┌───────────────┐         ┌──────────────────────────────────────┐  │
  │   │  Open WebUI   │  /v1    │            hermes-agent              │  │
  │   │  (web front   │ ───────►│              gateway                 │  │
  │   │   door, email/│  SSE    │   ┌────────────────────────────────┐ │  │
  │   │   pw login,   │ ◄───────│   │ local OpenAI-compat HTTP server│ │  │
  │   │   per-user)   │         │   └────────────────────────────────┘ │  │
  │   └───────────────┘         │   ┌────────────────────────────────┐ │  │
  │          ▲                  │   │ Discord / Slack gateway (@tag) │ │  │
  │          │                  │   └────────────────────────────────┘ │  │
  │   teammates' browsers       │              │ delegates via          │  │
  │   + Discord/Slack tags      │              ▼ terminal backend       │  │
  │                             │   ┌────────────────────────────────┐ │  │
  │                             │   │  claude (v1 spine; per-user     │ │  │
  │                             │   │  subscription token)            │ │  │
  │                             │   └────────────────────────────────┘ │  │
  │                             └───────────┬──────────────┬───────────┘  │
  │                                         │ DATABASE_URL │ MCP           │
  │                              Railway vol │              │              │
  │                              HERMES_HOME │              ▼              │
  │                              (/opt/data) ▼     ┌──────────────────┐    │
  │                             ┌──────────────┐   │ gbrain (shared   │    │
  │                             │ Postgres +   │◄──│ team brain;      │    │
  │                             │ pgvector     │   │ search/think/    │    │
  │                             │ (users,usage,│   │ capture via MCP) │    │
  │                             │  knowledge)  │   └──────────────────┘    │
  │                             └──────────────┘                          │
  └──────────────────────────────────────────────────────────────────────┘
            ▲
            │  operator SSH (Railway shell) → fix/debug without redeploy
```

**Request flow for "give a task, get output":**

1. Teammate logs into Open WebUI (email/password), picks the `hermes-agent` model, types a
   task.
2. Open WebUI calls `POST /v1/chat/completions` with `Authorization: Bearer <local key>`;
   the login + task are recorded for usage tracking.
3. The local server builds the user's session and runs the agent loop on **their** token.
4. The agent runs Claude Code on the box via the terminal backend (`pty=true`,
   `background=true` for long jobs), optionally consulting the shared brain over MCP
   (`search`/`capture`), polling for progress.
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
5. **Managed Postgres (pgvector)** — Railway's one-click pgvector Postgres as a third
   service; the box reads `DATABASE_URL`. This is the durable backbone for users, usage
   tracking, and shared knowledge (Epic D). Backups enabled.
6. **gbrain (shared brain) — day-one foundation** — deploy gbrain as a service on the same
   pgvector Postgres and expose it to Claude Code + the orchestrator over **MCP**
   (`search`/`think`/`capture`). Committed, not gated — stands up with the rest of the
   foundation.
7. **Operator SSH** — document the Railway shell as the "remote in and fix it" path;
   note that SSH is also a first-class terminal backend if we later want the box to
   reach *other* machines.

---

## Phased rollout

- **Phase 0 — Pipe test (Option A, single token).** Slim `Dockerfile.railway` +
  `railway.json`, Claude Code baked in, **one operator's `CLAUDE_CODE_OAUTH_TOKEN`**
  (subscription, no API key), local server on. Verify `claude` runs on the box on the
  subscription and streams back through `/v1`. *Exit:* a task via `curl` produces real
  Claude Code output with **no API charge**. (Single token here only proves wiring.)
- **Phase 1 — Web front door + shared brain (day-one foundation).** Bundle Open WebUI as a
  Railway service pointed at `/v1` with email/password accounts; stand up the **pgvector
  Postgres** + **gbrain** services and wire gbrain to Claude Code over MCP. *Exit:* a
  teammate logs into a URL, types a task, watches it run, and the agent can `search` /
  `capture` against the shared brain.
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

## Implementation plan (build order)

Everything lives in a new self-contained `railway/` directory plus a small, additive
amount of new code inside hermes for per-user tokens and the shared-brain wiring. Each
step lists the **artifacts** to create and the **acceptance criteria** it satisfies. Steps
ship as small commits on `claude/railway-plugin-llm-integration-FvfBA`; the PR flips from
draft to ready when Step 1 (Phase 0) is green on Railway.

### Step 0 — Scaffolding (no behavior change)
- **Artifacts:** `railway/` directory, `railway/README.md` (deploy guide skeleton),
  `railway/.env.railway.example` (every env var documented).
- **Done when:** structure is in place and documented; nothing else references it yet.

### Step 1 — Phase 0 / Epic A: the agent box (P0)
- **Artifacts:**
  - `railway/Dockerfile.railway` — slim Debian + python3 + nodejs; `pip install` hermes
    with a minimal extras set (gateway + local server); `npm i -g
    @anthropic-ai/claude-code`. No Playwright/WhatsApp/ffmpeg.
  - `railway/railway.json` — build from `Dockerfile.railway`; deploy with `/health`
    healthcheck, restart-on-failure, and a volume mounted at `HERMES_HOME=/opt/data`.
  - `railway/entrypoint.sh` — **startup guardrail**: hard-fail with a clear message if
    `ANTHROPIC_API_KEY` (or any model-billing key) is set; verify `CLAUDE_CODE_OAUTH_TOKEN`
    present; then launch `hermes gateway` with `API_SERVER_ENABLED=true`.
- **Satisfies:** A1 (deploy, `/health`, `claude --version`, volume persists), A2 (token in →
  output out, guardrail, zero API spend).
- **Verify:** deploy to Railway; `curl /health`; `curl /v1/chat/completions` returns real
  Claude Code output; confirm Anthropic console shows **zero** API usage; boot with a dummy
  `ANTHROPIC_API_KEY` and confirm it refuses to start.
- **Gate:** when this is green, **flip the PR to ready-for-review.**

### Step 2 — Phase 1 / Epic B: web front door + login + usage tracking (P0)
- **Artifacts:**
  - `railway/openwebui.md` + `railway/openwebui.railway.json` — Open WebUI as a second
    Railway service: `OPENAI_API_BASE_URL` → hermes `/v1`, `OPENAI_API_KEY` →
    `API_SERVER_KEY`; **email/password auth on, SSO off**, admin-managed signups.
  - Usage tracking: enable Open WebUI's user/activity records; capture source IP/location
    at the proxy; pass the logged-in user identity to hermes via header so each task is
    attributed per user.
- **Satisfies:** B1 (login), B2 (who/when/where + per-task attribution, no secrets logged),
  B3 (streamed output).
- **Verify:** create an account, log in, run a task, see it streamed; confirm a login +
  task row with user/time/IP exists; confirm no token/password in logs.

### Step 3 — Phase 1 / Epic D: modern database + gbrain shared brain (P0, day-one)
- **Artifacts:**
  - Railway one-click **pgvector Postgres** service; hermes + gbrain read `DATABASE_URL`.
  - `railway/gbrain.md` + `railway/gbrain.railway.json` — gbrain deployed on the same
    pgvector DB.
  - MCP wiring: register gbrain's MCP server with **both** the hermes orchestrator and the
    Claude Code CLI (`.mcp.json` / `claude mcp add`) so `search`/`think`/`capture` are
    available during tasks.
- **Satisfies:** D1 (Postgres system of record, backups), D2 (gbrain over MCP, permission
  scoping, available day one).
- **Verify:** agent calls `search`/`capture`; knowledge persists across redeploys; user A's
  private capture is not visible to user B.

### Step 4 — Phase 2 / Epic C: personal agents on per-user tokens (P0) — *most new code*
- **Artifacts (new hermes code, additive):**
  - A small **encrypted per-user credential store** in Postgres keyed by Open WebUI user.
  - A **token-entry flow** (chat command / lightweight settings hook) so a teammate pastes
    their own `setup-token`; it's validated (`claude` auth check) and stored.
  - Delegation wiring so each user's Claude Code subprocess runs with **their**
    `CLAUDE_CODE_OAUTH_TOKEN` in its environment (per-session isolation).
- **Satisfies:** C1 (own token, isolated rate limits, rotate/revoke), C2 (per-user memory
  isolation), C3 (`@tag` from Discord/Slack).
- **Verify:** two users with different tokens run concurrently; one hitting their limit does
  not throttle the other; private memory stays private.
- **Risk:** this is the part with real new code and the most uncertainty — built and
  reviewed on its own commit.

### Step 5 — Phase 3 / Epic E: overnight prep + OpenClaw (P1)
- **Artifacts:** cron task config for unattended overnight jobs with per-user delivery;
  `railway/openclaw-migration.md` documenting `hermes claw migrate`.
- **Satisfies:** E1 (overnight delivery, attributed), E2 (OpenClaw import via dry-run).

### Step 6 — Phase 4 / Epic F: team rollout + hardening (P1/P2)
- **Artifacts:** rate-limit handling (graceful "throttled, retry" with backoff),
  `railway/RUNBOOK.md` (SSH break-glass), secret-hygiene/log-redaction review; add the
  rest of the team as accounts. Usage dashboards remain **P2**, out of scope for now.
- **Satisfies:** F1 (add accounts, no refactor), F2 (rate-limit UX + runbook).

### Sequencing notes
- Steps 1→3 are the **day-one foundation** and should land together-ish for a usable PoC.
- Step 4 is the largest engineering lift; everything before it is mostly config + a
  guardrail script, so we de-risk by shipping the foundation first.
- Each step is independently verifiable against its acceptance criteria before the next.

---

### Decided

- ✅ **No model-billing API anywhere** — all-Claude subscription, both layers. The
  orchestrator brain stays on Claude (no separate Nous subscription) until/unless rate
  limits force a split.
- ✅ **Provisioning** — Option B, multi-user from day one; PoC with 2–3 own-subscription
  teammates, then open to the team.
- ✅ **v1 CLI** — Claude Code only is the spine; Codex / OpenCode / OpenClaw deferred
  (subscription-only when added).
- ✅ **Topology** — single shared box (B); per-teammate services (C) only if blast radius
  bites at full scale.
- ✅ **Auth** — simple **email + password** accounts (admin sets the password). **No SSO.**
  Purpose is lightweight identity + **usage tracking** (who logged in, when, from where),
  not enterprise IAM.
- ✅ **Plan tier** — the 2–3 PoC teammates are on **Max** (confirmed), which is what
  unattended overnight work needs.
- ✅ **Shared memory / database** — **modern database is day-one foundation.** Railway's
  one-click **pgvector Postgres** is the durable backbone, and **gbrain** (Postgres +
  pgvector, MCP-native, integrates with Claude Code) ships **on day one** as the shared
  synthesized team brain — committed, not a spike. Coexists with hermes's per-user memory.
  See Epic D.
- ✅ **Usage-tracking depth** — login + per-task attribution (who/when/where) is the
  approved scope for now. Aggregate dashboards (tasks/day per user) are a later **P2**
  enhancement, not required for the PoC.

---

## User stories & acceptance criteria

> Product framing: maximize what Claude + agents can do for the team while keeping the box
> low-maintenance and ToS-clean. Stories are grouped into epics that map to the phased
> rollout. Each story has **Given/When/Then** acceptance criteria that must pass before we
> push code for that story. Priority: **P0** = blocks PoC, **P1** = needed for team
> rollout, **P2** = enhancement.

### Definition of Done (applies to every story)

- Acceptance criteria below are demonstrably met (manual run or test).
- No `ANTHROPIC_API_KEY` (or any model-billing key) reachable by the process — verified.
- Change is documented in the deploy guide and committed to the feature branch.
- Secrets (tokens, DB creds, passwords) are never logged or committed.

### Epic A — Stand up the agent box on Railway (Phase 0) · P0

**A1 — One-command Railway deploy.**
*As an operator, I want to deploy the agent box to Railway from the repo so that the
environment stands up without manual setup.*
- **Given** the repo with `railway.json` + `Dockerfile.railway`, **when** I deploy,
  **then** the service builds, `/health` returns 200, and the `claude` CLI is present
  (`claude --version` succeeds inside the container).
- **Given** a redeploy, **when** the container is replaced, **then** `HERMES_HOME`
  (`/opt/data`) persists on the mounted volume (sessions/skills survive).
- **Given** the slim image, **then** cold start is materially faster than the existing
  "everything" image (no Playwright/WhatsApp/ffmpeg).

**A2 — Drop in a Claude token, prove no API billing.**
*As an operator, I want to set one Claude subscription token and have Claude run, with
zero API spend, so that the no-API goal is proven end to end.*
- **Given** `CLAUDE_CODE_OAUTH_TOKEN` set and `ANTHROPIC_API_KEY` unset, **when** I send a
  task via `curl` to `/v1`, **then** I get real Claude Code output streamed back.
- **Given** the container boots, **when** `ANTHROPIC_API_KEY` is detected in the
  environment, **then** startup **fails loudly** with a clear error (guardrail against the
  billing footgun).
- **Given** a completed task, **when** I check the Anthropic console, **then** API usage is
  **zero** (work was billed to the subscription).

### Epic B — Web front door + login + usage tracking (Phase 1) · P0

**B1 — Email/password login (no SSO).**
*As a teammate, I want to log into a web URL with an email and a password set by the admin
so that only known people can submit tasks.*
- **Given** Open WebUI with email/password auth enabled and SSO disabled, **when** an admin
  creates an account with a set password, **then** that user can log in and a stranger
  cannot.
- **Given** wrong credentials, **when** a user submits them, **then** access is denied and
  the attempt is recorded.

**B2 — Usage tracking (who, when, where).**
*As the owner, I want every login and task attributed to a person so that I can see who is
using the box and from where.*
- **Given** a successful login, **when** it happens, **then** a record captures user email,
  timestamp, and source IP/approximate location.
- **Given** any submitted task, **when** it runs, **then** it is attributed to the
  logged-in user and is reviewable later (per-user activity view or exportable log).
- **Given** the tracking store, **then** it contains no plaintext passwords or tokens.

**B3 — Task in → streamed output.**
*As a teammate, I want to type a task and watch streamed output so that I get results in
the browser without touching a terminal.*
- **Given** I'm logged in, **when** I submit a task, **then** Claude Code output streams
  back live (SSE) and long tasks run in the background with visible progress.

### Epic C — Personal agents on each person's own subscription (Phase 2 PoC, 2–3 on Max) · P0

**C1 — Paste my own Claude token once.**
*As a teammate, I want to paste my own `claude setup-token` once so that my tasks run on
**my** Max subscription and my rate limits are isolated from everyone else's.*
- **Given** I'm logged in, **when** I paste my `setup-token`, **then** it is validated
  (`claude` auth check), stored scoped to my account, and persisted on the volume.
- **Given** my token is stored, **when** I run a task, **then** it executes under **my**
  subscription (not a shared one), and another user hammering their limit does not throttle
  me.
- **Given** I need to rotate/revoke, **when** I replace or clear my token, **then** old
  credentials are removed and no longer usable.

**C2 — My agent remembers my context.**
*As a teammate, I want my agent to recall my past work across sessions so that it builds on
prior context.*
- **Given** prior sessions, **when** I start a new one, **then** my agent can recall my
  earlier work, and **cannot** see another user's private session memory.

**C3 — @tag my personal agent from chat.**
*As a teammate, I want to @tag my agent in Discord/Slack so that I can hand off legwork from
where I already work.*
- **Given** the gateway is enabled and my chat identity is linked, **when** I @tag the
  agent, **then** it runs the task as my personal agent and delivers the result back to the
  channel.

### Epic D — Modern shared database / team brain (day-one foundation) · P0

> **Committed, not a spike.** gbrain ships on **day one** as the shared team brain — it's
> part of the foundation alongside the agent box and web front door, not a later
> evaluation. hermes's built-in per-user memory (SQLite/FTS5/Honcho) **coexists**: it
> holds each person's private session memory, while gbrain is the **shared, synthesized
> cross-team knowledge graph** every agent reads from and writes to.

**D1 — A modern database as system of record.**
*As the team, we want a modern managed database so that everything (users, usage, memory,
shared knowledge) is connected and durable, not scattered in flat files.*
- **Given** a Railway one-click **pgvector Postgres** service, **when** the box connects via
  `DATABASE_URL`, **then** users/usage/shared-knowledge persist in Postgres and survive
  redeploys, with backups enabled.

**D2 — Shared synthesized team brain via gbrain.**
*As an agent and as a teammate, I want a shared, synthesized knowledge layer that every
person's agent can query and contribute to, exposed over MCP, so that the team's knowledge
compounds instead of living in one person's head.*
- **Given** gbrain deployed (Postgres + pgvector) and wired to Claude Code + the
  orchestrator over **MCP**, **when** an agent calls `search` / `think` / `capture`,
  **then** it returns synthesized answers with citations and can persist new knowledge.
- **Given** the multi-user setup, **when** user A captures private knowledge, **then** user
  B cannot read it unless it's shared (permission scoping respected).
- **Given** day-one rollout, **when** a teammate runs their first task, **then** the shared
  brain is already available to consult — no separate enablement step.

> *Risk acknowledged (PO note):* committing to gbrain day-one puts a TS service on the
> critical path. Mitigation: it sits on the same managed pgvector Postgres we're standing
> up anyway, and the underlying `DATABASE_URL` data is usable directly if gbrain ever needs
> to be bypassed. This is a noted risk, **not** a gate.

### Epic E — Overnight prep + OpenClaw (Phase 3) · P1

**E1 — Overnight prep delivered by morning.**
*As a teammate, I want to schedule prep/legwork to run unattended overnight so that finished
work is waiting in the morning.*
- **Given** a scheduled cron task, **when** it runs overnight on my subscription, **then**
  the result is delivered to my channel/inbox before the workday, attributed to me.

**E2 — OpenClaw migration.**
*As a teammate coming from OpenClaw, I want my config/skills imported so that I don't start
from scratch.*
- **Given** `~/.openclaw` data, **when** I run `hermes claw migrate`, **then** my config and
  skills are imported (validated by a dry-run preview first).

### Epic F — Team rollout + hardening (Phase 4) · P1/P2

**F1 — Open to the team with no refactor.**
*As the owner, I want to add the rest of the team as accounts so that rollout is a config
change, not a rewrite.*
- **Given** Option B, **when** I add N more email/password accounts + their own tokens,
  **then** they work exactly like the PoC users with no code change.

**F2 — Operate it safely.**
*As an operator, I want rate-limit handling, secret hygiene, and a runbook so that the box
stays healthy and break-glass SSH fixes are documented.*
- **Given** a user hits their Claude rate limit, **when** it happens, **then** the agent
  surfaces a clear "throttled, retry later" state (with backoff) rather than a raw error.
- **Given** an incident, **when** an operator SSHes into the Railway shell, **then** the
  runbook documents the common fixes without needing a redeploy.

### Still open

*None blocking.* All scoping decisions are resolved (no-API/all-Claude, Option B multi-user,
Claude Code v1 spine, email/password + usage tracking, Max tier, gbrain day-one,
tracking depth). Design is ready to build against the acceptance criteria above. The only
deferred item is the **P2** usage dashboards, intentionally out of PoC scope.

---

## Why this is low-maintenance (the original goal)

- The box runs **one image** with the CLI and skills baked in — no per-developer setup.
- **Open WebUI** handles email/password accounts + UI so we maintain zero custom frontend.
- **Managed Postgres (pgvector)** on Railway is the durable backbone — no DB to babysit.
- **Persistent volume** means redeploys don't wipe memory or skills.
- **SSH-in** gives operators a break-glass path without touching the team's workflow.
- Everything sits on **existing hermes-agent infrastructure**, so we inherit its
  sessions, skills, cron, and multi-platform gateways instead of reinventing them.
- **No API billing** — runs entirely on teammates' existing Claude Max subscriptions
  via `setup-token`, so cost is the flat subscription fee, nothing per-token.
