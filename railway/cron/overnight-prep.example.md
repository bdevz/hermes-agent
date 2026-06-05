# Overnight prep jobs (Epic E1)

The goal you described: teammates hand off legwork that runs unattended
overnight, so finished work is waiting in the morning. hermes ships a cron
scheduler; each job runs on a teammate's own subscription and delivers results
to their channel.

## Schedule a job

```bash
# inside the box
hermes cron add \
  --name "alice-morning-brief" \
  --schedule "0 6 * * *" \
  --deliver "telegram:@alice" \
  --prompt "Pull yesterday's PRs and open issues, summarize what needs my
            attention today, and draft replies for anything urgent."
```

## Run it on the right person's subscription

Overnight jobs must bill to the requesting teammate, not a shared token. Run the
coding portion through the per-user delegation path so it uses their token and
records attribution:

```bash
claude-as-user alice -p "…prep task…"
```

(See `railway/README.md` → Step 4 integration for how the gateway passes the
user id.)

## Acceptance (E1)

- A scheduled job runs overnight under the requester's subscription.
- The result is delivered to their channel before the workday.
- The run is attributed to them in `agentbox` usage tracking.

> **Rate limits:** overnight unattended work is exactly where Pro throttles and
> **Max** holds up. The PoC teammates are on Max for this reason.
