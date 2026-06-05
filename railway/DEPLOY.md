# Connecting this repo to Railway (3 ways)

You can connect the cloud repo to Railway any of three ways. They all deploy the
**agent box** service from this repo using `railway/railway.json` (which builds
`railway/Dockerfile.railway`). Pick one — most teams use **A** for day-to-day and
keep **B/C** for token-based ("API") deploys from CI or a script.

> **Tokens at a glance**
> - **Project token** → env var `RAILWAY_TOKEN`. Scoped to one project/environment,
>   deploy-only. This is the one for CI/scripts.
> - **Account/workspace token** → env var `RAILWAY_API_TOKEN`. Broader; for
>   account-level automation.

## A. GitHub integration (auto-deploy on push) — easiest

1. Railway → **New Project → Deploy from GitHub repo** → pick
   `bdevz/hermes-agent`.
2. Choose the branch `claude/railway-plugin-llm-integration-FvfBA`.
3. In the service → **Settings → Config-as-code**, set the path to
   `railway/railway.json`.
4. **Settings → Variables:** add `API_SERVER_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`
   (see `.env.railway.example`). **Do not** add `ANTHROPIC_API_KEY`.
5. **Settings → Volumes:** add a volume mounted at `/opt/data`.

Railway redeploys automatically on every push to that branch. No token needed.

## B. Token-based deploy from a script (the "reconnect via API" path)

Exactly the flow you've used before — a project token, no interactive login:

```bash
npm i -g @railway/cli                 # or: bash <(curl -fsSL cli.new)
export RAILWAY_TOKEN=<project-token>   # Railway → project → Settings → Tokens
./railway/deploy.sh <service-name>     # omit name if the token is service-scoped
```

`deploy.sh` runs `railway up --ci` with the token in the environment. Use this to
redeploy from your laptop, a server, or to "reconnect" a project after the fact.

## C. GitHub Actions (token-based CI deploy)

`.github/workflows/railway-deploy.yml` is already in the repo. To enable it:

1. Create a **project token** in Railway.
2. Repo → **Settings → Secrets and variables → Actions**:
   - secret `RAILWAY_TOKEN` = the project token
   - (optional) variable `RAILWAY_SERVICE` = the service name/ID
3. It deploys on a **push to the feature branch that touches `railway/**`**, or
   manually from the **Actions** tab → "Deploy to Railway" → **Run workflow**.
   After deploying it runs a **Phase-0 check**: polls `/health`, and (if you add a
   repo secret `API_SERVER_KEY`) runs a zero-API-spend chat smoke test. If the
   public domain can't be auto-resolved, set repo variable `RAILWAY_PUBLIC_DOMAIN`.

> Why a push trigger (not just manual): `workflow_dispatch` only works when the
> workflow lives on the **default branch**. Triggering on push to the feature
> branch lets the deploy be kicked by a commit while the work is still on the PR.

## After connecting — verify Phase 0

```bash
curl -s https://<your-domain>/health        # → 200
# real Claude Code output, zero API spend:
curl -s https://<your-domain>/v1/chat/completions \
  -H "Authorization: Bearer $API_SERVER_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"hermes-agent","messages":[{"role":"user","content":"have claude code print hello"}]}'
```

Then add the **Postgres (pgvector)** and **gbrain** services from `gbrain.md`, and
the **Open WebUI** service from `openwebui.md`. Each is its own Railway service in
the same project; they connect via shared variables (`DATABASE_URL`,
`API_SERVER_KEY`, `GBRAIN_MCP_URL`).

## Multi-service layout in one Railway project

```
Railway project
├── agent-box        (this repo, railway/railway.json)         ← A/B/C above
├── open-webui       (ghcr.io/open-webui/open-webui:main)      ← openwebui.md
├── postgres         (pgvector template)                       ← gbrain.md
└── gbrain           (github.com/garrytan/gbrain)              ← gbrain.md
```

## Troubleshooting

- **"Project Token Not Found"** in CI → the `RAILWAY_TOKEN` secret is missing or
  is an account token where a project token is required. Recreate a *project*
  token and re-add the secret.
- **Build ignores the Dockerfile** → the service's config-as-code path isn't set
  to `railway/railway.json`.
- **Box won't start, "model-billing API key detected"** → remove
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` from the service variables (this box is
  subscription-only).
