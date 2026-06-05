# Shared database + gbrain team brain (Epic D — day-one foundation)

A **modern database** is part of the foundation, not a later add-on. Railway's
one-click **pgvector Postgres** is the durable system of record, and
[**gbrain**](https://github.com/garrytan/gbrain) is the shared, synthesized team
brain on top of it — MCP-native and already integrated with Claude Code.

**How it coexists with hermes memory:** hermes's built-in per-user memory
(SQLite/FTS5/Honcho) holds each person's *private* session memory. gbrain is the
*shared* cross-team knowledge graph every agent can `search` and `capture`
against. Different roles, not duplicates.

## 1. Postgres (pgvector)

1. Add Railway's **pgvector Postgres** template to the project (one click).
2. Reference its URL into the agent box service:
   `DATABASE_URL=${{Postgres.DATABASE_URL}}`.

That alone upgrades the agent box: `agentbox` automatically uses the Postgres
backend for the **per-user credential store** and **usage tracking** when
`DATABASE_URL` is set (tables `agentbox_kv`, `agentbox_log` are created on first
use). No code change — just the variable.

## 2. gbrain service

1. New Railway service from `https://github.com/garrytan/gbrain` (TypeScript /
   PGLite or Postgres + pgvector).
2. Point it at the **same** pgvector Postgres (`DATABASE_URL`), or let it manage
   its own schema there.
3. Expose its MCP endpoint; note the URL + auth token as `GBRAIN_MCP_URL` /
   `GBRAIN_MCP_TOKEN`.

## 3. Wire gbrain over MCP

**To the hermes orchestrator** — paste `config/mcp_servers.example.yaml` into
`$HERMES_HOME/config.yaml` and set `GBRAIN_MCP_URL` / `GBRAIN_MCP_TOKEN`.

**To Claude Code** (so delegated tasks can consult the brain):

```bash
claude mcp add --transport http gbrain "$GBRAIN_MCP_URL" \
  --header "Authorization: Bearer $GBRAIN_MCP_TOKEN"
```

## Acceptance checks (D1/D2)

- Agent calls `search` / `capture`; results return with citations and persist.
- Knowledge survives a redeploy (it's in Postgres, not the ephemeral container).
- Multi-user scoping: user A's *private* capture is not visible to user B unless
  shared.

## PO note (risk acknowledged, not a gate)

Committing to gbrain day-one puts a TypeScript service on the critical path.
Mitigation: it rides the same managed Postgres we stand up anyway, and the raw
`DATABASE_URL` data is usable directly if gbrain ever needs to be bypassed.
