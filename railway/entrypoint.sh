#!/usr/bin/env bash
#
# Railway entrypoint for the LLM-CLI agent box.
#
# Responsibilities:
#   1. GUARDRAIL: refuse to start if a pay-per-token model-billing key is
#      present. The whole point of this box is to run on a Claude *subscription*
#      (CLAUDE_CODE_OAUTH_TOKEN). If ANTHROPIC_API_KEY is set, Claude Code would
#      silently bill the API instead of the subscription — so we fail loudly.
#   2. Bootstrap config/skills into the mounted volume (HERMES_HOME).
#   3. Bind the local OpenAI-compatible server to 0.0.0.0:$PORT so the Open
#      WebUI service (and Railway healthchecks) can reach it.
#   4. Launch `hermes gateway`.
#
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-/opt/data}"
INSTALL_DIR="/opt/hermes"

# ---------------------------------------------------------------------------
# 1. No-API guardrail (Epic A / AC A2)
# ---------------------------------------------------------------------------
# Claude Code prefers ANTHROPIC_API_KEY over the subscription if both are
# present, which would route work to pay-per-token billing. This box is
# subscription-only, so any model-billing key is a hard error.
_billing_keys=()
for _k in ANTHROPIC_API_KEY OPENAI_API_KEY; do
    if [ -n "${!_k:-}" ]; then
        _billing_keys+=("$_k")
    fi
done
if [ "${#_billing_keys[@]}" -gt 0 ]; then
    echo "FATAL: model-billing API key(s) detected in the environment: ${_billing_keys[*]}" >&2
    echo "       This box runs on Claude *subscriptions* only (CLAUDE_CODE_OAUTH_TOKEN)." >&2
    echo "       A billing key would make Claude Code charge the API instead of the" >&2
    echo "       subscription. Remove it from the Railway service variables and redeploy." >&2
    echo "       (If you genuinely intend API billing, this is not the right image.)" >&2
    exit 1
fi

# A subscription token is required for the box-level operator agent. Per-user
# tokens (Epic C) are supplied at runtime and stored per account.
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "WARNING: CLAUDE_CODE_OAUTH_TOKEN is not set. The operator/default agent will" >&2
    echo "         not be able to run Claude Code until a subscription token is provided." >&2
    echo "         Generate one with 'claude setup-token' and set it as a service variable." >&2
fi

# ---------------------------------------------------------------------------
# 2. Bootstrap volume (mirrors docker/entrypoint.sh)
# ---------------------------------------------------------------------------
mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills}

if [ ! -f "$HERMES_HOME/.env" ] && [ -f "$INSTALL_DIR/.env.example" ]; then
    cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env"
fi
if [ ! -f "$HERMES_HOME/config.yaml" ] && [ -f "$INSTALL_DIR/cli-config.yaml.example" ]; then
    cp "$INSTALL_DIR/cli-config.yaml.example" "$HERMES_HOME/config.yaml"
fi
if [ ! -f "$HERMES_HOME/SOUL.md" ] && [ -f "$INSTALL_DIR/docker/SOUL.md" ]; then
    cp "$INSTALL_DIR/docker/SOUL.md" "$HERMES_HOME/SOUL.md"
fi
if [ -d "$INSTALL_DIR/skills" ] && [ -f "$INSTALL_DIR/tools/skills_sync.py" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py" || true
fi

# ---------------------------------------------------------------------------
# 3. Network binding for Railway
# ---------------------------------------------------------------------------
# Railway injects $PORT and expects the service to listen on it, on 0.0.0.0.
export API_SERVER_ENABLED="${API_SERVER_ENABLED:-true}"
export API_SERVER_HOST="${API_SERVER_HOST:-0.0.0.0}"
export API_SERVER_PORT="${API_SERVER_PORT:-${PORT:-8642}}"

echo "Starting hermes gateway (API server on ${API_SERVER_HOST}:${API_SERVER_PORT}, subscription-only)..." >&2

# ---------------------------------------------------------------------------
# 4. Launch
# ---------------------------------------------------------------------------
# Default to `gateway`; allow overriding the subcommand via `docker run ... <cmd>`.
if [ "$#" -eq 0 ]; then
    set -- gateway
fi
exec hermes "$@"
