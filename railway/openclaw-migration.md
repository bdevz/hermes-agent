# OpenClaw migration (Epic E2)

"Armi's agent" / "OpenClaude" = **OpenClaw**. hermes ships a first-class
migration that imports an existing `~/.openclaw` setup (config + skills).

## Migrate

```bash
# preview first — non-destructive
hermes claw migrate --dry-run

# then apply
hermes claw migrate

# optional: archive leftover OpenClaw dirs afterward
hermes claw cleanup --dry-run
hermes claw cleanup
```

Presets and conflict handling:

```bash
hermes claw migrate --preset full --overwrite
```

## On the Railway box

A teammate coming from OpenClaw can either:

- run the migration in their box session so their skills/config come along, or
- start fresh — OpenClaw migration is optional, not required.

## Acceptance (E2)

- `hermes claw migrate` (after a clean dry-run preview) imports config + skills
  without clobbering anything unexpectedly.
