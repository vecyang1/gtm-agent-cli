# Contributing

Keep the project focused on the agent safety layer around Google Tag Manager.

Run before sending changes:

```bash
go mod verify
go test ./...
go vet ./...
go build -o ./gtm-agent ./cmd/gtm-agent
./scripts/e2e-fake-gtm.sh
```

Do not commit live snapshots, backups, tokens, service-account files, or customer/business-specific GTM configuration.

When an improvement belongs to raw GTM command coverage rather than the safety layer, consider contributing it upstream to [`owntag/gtm-cli`](https://github.com/owntag/gtm-cli).

