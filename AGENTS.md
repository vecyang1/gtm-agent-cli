# Agent Instructions

- Use the existing wheel first: `@owntag/gtm-cli` is the upstream GTM command surface.
- Keep `gtm-agent` focused on safety, orchestration, snapshots, diffs, plans, backups, and verification.
- Never commit service-account keys, tokens, live snapshots, or backups.
- Do not add a publish path that bypasses `--allow-publish --confirm <container-id>`.
- Use fake-upstream tests for normal verification.
- Run `go test ./...`, `go vet ./...`, and `./scripts/e2e-fake-gtm.sh` before claiming completion.

