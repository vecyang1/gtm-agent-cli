# GTM Container Version History Archival, Semantic Diffs, and Change Explorer

`gtm-agent history` archives published Google Tag Manager container versions read-only (`GET` only, zero workspace mutations or publishes), computes chronological semantic and line-by-line code diffs, unpacks normalized human-readable resources, replays each version as a chronological commit into an isolated private Git repository, and generates a self-contained Change Explorer web interface.

## Native `gtm-agent diff` Support for `ContainerVersion` JSON

Both Go core (`gtm-agent diff`) and Python tooling accept:

1. `gtm-agent snapshot` JSON (`schemaVersion: "1"`).
2. Raw GTM API `ContainerVersion` JSON (`versions get`, `versions live`, `backup`).
3. GTM UI Export JSON (`exportFormatVersion: 2` with nested `containerVersion`).

All volatile GTM keys (`fingerprint`, `path`, `tagManagerUrl`, `workspaceId`) are stripped and resource collections (`tag` -> `tags`, etc.) normalized before semantic comparison so timestamps or workspace hops never produce false diffs.

## Subcommands

| Subcommand | Purpose | Key Options |
| :--- | :--- | :--- |
| `gtm-agent history archive` | Read-only fetch of all or subset versions, build artifacts, optional unpack, UI, and private Git replay | `--account-id`, `--container-id`, `--out`, `--versions`, `--limit`, `--refresh`, `--unpack`, `--ui`, `--git-repo` |
| `gtm-agent history build` | Build `versions_index.json`, `diff_series.json`, `CHANGELOG.md`, `latest/`, and `history_viewer.html` offline from existing `gtm_v*.json` files | `--dir`, `--out` |
| `gtm-agent history diff` | Compute exact structured semantic + code diff between any two archived version files | `--before`, `--after`, `--out`, `--format {json,md}` |
| `gtm-agent history git-replay` | Replay archived versions chronologically as Git commits + tags (`v01`..`vN`) using GTM fingerprint UTC timestamps | `--dir`, `--git-repo` |
| `gtm-agent history serve` | Launch local HTTP server with History API deep-linking (`/timeline`, `/compare`, `/search`, `/inspector`) and `/api/{overview,diff,search,trace}` | `--dir`, `--port`, `--host` |

## Safety & Privacy Boundaries

- **Read-Only API Calls**: `archive` uses `gtm version-headers list` and `gtm versions get` only. It never calls `versions create`, `versions publish`, or any workspace mutation.
- **Public Repo Guard (`assert_safe_output_dir`)**: Refuses writing client container archives inside un-ignored paths of the public `gtm-agent-cli` repository unless `--allow-unsafe-out` is explicitly passed.
- **No Nested `.git` Repositories (`assert_safe_git_repo`)**: Refuses initializing a Git replay repo inside an existing parent repository tree (e.g., `knowledge vault`). Keep `git-replay` repositories in an external private path such as `~/.local/share/gtm-agent/private-git-history/<brand>-<account>-<container>`.

## Storage & Unpacking Layout

Inside an archived output directory:

- `gtm_v01.json` .. `gtm_vN.json`: Complete raw GTM `ContainerVersion` JSON per version.
- `versions_index.json`: Version timeline metadata, resource counts, per-version UTC timestamp derived from `fingerprint`, and delta counts.
- `diff_series.json`: Machine-readable transition ledger + per-field & code diff hunks across all consecutive versions.
- `CHANGELOG.md`: Human-readable chronological changelog highlighting added, modified, and removed tags, triggers, variables, templates, and code snippets.
- `latest/`: Normalized latest container breakdown (`tags/*.html`, `variables/*.js`, `templates/*.tpl`, `_resolved/*.json` with trigger/folder names resolved).
- `history_viewer.html`: Single-file offline Change Explorer with Timeline, Arbitrary `vA -> vB` Compare + colored line diffs, Global Search, and Rule Inspector + Entity Lifecycle Tracer.
