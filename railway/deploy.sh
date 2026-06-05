#!/usr/bin/env bash
#
# Deploy the agent box to Railway from anywhere using a PROJECT TOKEN — no
# interactive login. This is the "reconnect via API/token" path.
#
# Prereqs:
#   - Railway CLI installed:  npm i -g @railway/cli   (or: bash <(curl -fsSL cli.new))
#   - A Railway project token: Railway → project → Settings → Tokens
#   - The service exists and its config path is set to `railway/railway.json`
#
# Usage:
#   RAILWAY_TOKEN=xxxx ./railway/deploy.sh [service-name-or-id]
#
# If you omit the service, the project token's scoped service is used.
set -euo pipefail

if ! command -v railway >/dev/null 2>&1; then
    echo "Railway CLI not found. Install it: npm i -g @railway/cli" >&2
    exit 1
fi

if [ -z "${RAILWAY_TOKEN:-}" ]; then
    echo "RAILWAY_TOKEN is not set. Create a project token in Railway and export it:" >&2
    echo "  export RAILWAY_TOKEN=<project-token>" >&2
    exit 1
fi
export RAILWAY_TOKEN

SERVICE="${1:-}"
echo "Deploying agent box to Railway${SERVICE:+ (service: $SERVICE)}..."

if [ -n "${SERVICE}" ]; then
    railway up --service "${SERVICE}" --ci
else
    railway up --ci
fi

echo "Done. Check: railway logs   and   curl https://<your-domain>/health"
