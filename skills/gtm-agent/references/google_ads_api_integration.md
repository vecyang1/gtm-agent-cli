# Google Ads API Integration and Tooling Reference

This reference document outlines the authentication and integration protocols for interacting with the Google Ads API, specifically comparing direct local execution (such as `google-ads-open-cli`) and managed middleware platforms (such as `Composio`).

## Google Ads API Authentication Architecture

To call the Google Ads API, any integration or application must satisfy Google's authentication requirements. These requirements consist of two separate layers:

1. **Identity & Authorization (OAuth 2.0)**:
   * Identifies the Google account executing the commands.
   * Requires a Google Cloud Console Project with OAuth client credentials (`client_id`, `client_secret`) and user consent.
   * Generates a Refresh Token to automate continuous access.
2. **Developer Identification (Developer Token)**:
   * A 22-character alphanumeric token that identifies the developer application itself.
   * Governed by Google's API Access policy to prevent abuse and enforce developer quotas.
   * Must be applied for manually via the **API Center** page in a Google Ads **Manager Account (MCC)**.
   * Basic Access (free, up to 15,000 operations/day) requires a brief manual review by Google's policy team.

## Tooling Comparison & API Setup Friction

When designing AI agent workflows to interact with Google Ads, the setup friction depends on the chosen integration lane:

### 1. Managed Middleware (e.g., Composio Google Ads Toolkit)
* **Auth Setup**: Bypasses the manual Developer Token application process.
* **Mechanism**: Composio provides a pre-configured platform integration for `Google Ads` (as well as `Metaads` and other ad platforms). When you authorize access via the Composio dashboard or CLI, they route the API requests through their own approved platform Developer Token.
* **Pros**: Ready to use immediately; zero wait time for developer token approval; handles OAuth token refresh automatically. Supports full write/mutate capabilities (e.g., `Mutate Campaigns` to create/update, `Mutate Ad Groups`, modifying ad group keywords, and adding/removing users from `Customer Lists` for audience targeting/offline conversions).
* **Cons**: Subjects operations to third-party pricing, rate limits, and latency; requires routing sensitive ad/campaign data through Composio's servers.

### 2. Direct Local Execution (e.g., `Bin-Huang/google-ads-open-cli` / Custom Scripts)
* **Auth Setup**: **Requires manual developer token application**.
* **Mechanism**: The CLI or Python script executes commands directly from your local terminal and sends requests directly to Google's endpoints. You must configure `developer_token`, `client_id`, and `client_secret` in a local `credentials.json` or `.env` file.
* **Pros**: Direct connection (low latency); 100% private (no data shared with third-party middleware); free to use up to standard Google Ads API quotas.
* **Cons**: High initial setup friction; requires waiting for Google to approve the developer token for production access (test accounts can use unapproved tokens but only against test ad accounts).

## Guidelines for AI Agents
* Before initializing a custom Google Ads script or local CLI tool, check the environment variables and local configs for an existing `DEVELOPER_TOKEN`.
* If a task requires zero-friction, instant prototyping and the client is okay with routing data through third-party platforms, recommend connecting via **Composio**.
* If the task requires high privacy, high performance, or long-term production scaling, guide the user to apply for a **Developer Token** via Google Ads Manager Account (MCC) API Center and use **google-ads-open-cli**.
