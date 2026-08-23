# Security

`gtm-agent` manages Google Tag Manager configuration, so treat it as production infrastructure tooling.

## Secrets

Do not commit:

- Google service-account JSON files
- OAuth tokens
- GTM exports containing private business context
- `.env` files
- Live snapshot or backup files

The default `.gitignore` excludes common secret and runtime artifact names.

## Mutations

`gtm-agent apply` is dry-run by default. A mutation requires `--execute`. Publishing requires both `--allow-publish` and `--confirm <container-id>`.

Use a dedicated GTM workspace for changes. Snapshot before and after every risky operation.

## Reporting

Open a private security advisory or issue if you find a leak risk, unsafe default, command injection risk, or behavior that can publish without the documented gates.

