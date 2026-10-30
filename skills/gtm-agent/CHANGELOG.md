# Changelog

All notable changes to the `gtm-agent` skill will be documented in this file.

## [1.3.0] - 2026-10-27

Web Supply Chain & Third-Party Script Security Audit Engine: added automated external script extraction, domain safety classification, deprecated/hijacked domain gatekeeper, and tag pause-state tracking into the portfolio weekly audit cadence (`CAD-20261019-portfolio-gtm-ga4-weekly-audit`).

### Added
- **Web Supply Chain & Third-Party Script Security Engine (`scripts/portfolio_gtm_audit.py`)**:
  - `extract_domains_from_html()`: parses Custom HTML tags for `<script src="...">`, inline string URLs, and protocol-relative endpoints.
  - `HIJACKED_OR_DEPRECATED_DOMAINS` Watchlist: gatekeeper blocking abandoned or hijacked vendor CDNs (e.g. `cdn.taku-app.com`, `taku-app.com`).
  - `APPROVED_VENDOR_DOMAINS` Catalog: whitelist verifying trusted tracking, analytics, and CRM vendors across Google, Meta, Clarity, Claspo, Taku, Encharge, NetroSEO, Leadsourcing, VisitorTracking, CX Genie, Chaport, Growify, and Nuwtonic.
  - **Tag Pause State Visibility**: audits and reports whether third-party tags are actively firing (`▶️ ACTIVE`) or safely paused/dormant (`⏸️ PAUSED`), honoring the invariant that deprecated scripts should be paused to preserve configuration history without client-side runtime risk.
  - **Markdown Report & JSON Matrix Enhancement**: generates the `## Web Supply Chain & External Script Security Audit` matrix across all 6 portfolio brands in `reports/runs/gtm-portfolio-audit.md`.
- **Unit Test Coverage (`tests/test_supply_chain_audit.py`)**:
  - Validates domain extraction from `<script src="...">`, inline DOM injection strings, protocol-relative URLs, hijacked domain flagging, and partner whitelist categorization.

## [1.2.0] - 2026-10-26

Cross-Domain Conversion Linker Synthesis & Hyphen-Tolerant E-Commerce Audit Check: added cross-domain linker domain decoration support in `gtm_autobuild.py`, hardened tag name pattern matching in `portfolio_gtm_audit.py`, and published container version 12 across `Acme Pet Care` (`189484691`) and `Learning with Vy` (`226299748`).

### Added
- **Cross-Domain Conversion Linker Synthesis (`scripts/gtm_autobuild.py`)**:
  - `GtmAutoBuilder` now extracts `linker_domains` from container configuration.
  - Automatically synthesizes cross-domain parameters for `gclidw` (`enableCrossDomain=true`, `acceptIncoming=true`, `linkerDomains=<domains>`, `urlPosition=query`), linking primary and storefront subdomains across third-party checkout rails.
- **Cross-Domain Linker Deployment**:
  - `Learning with Vy` (Container `226299748`, Version 12): Tag 16 `gclidw` firing on All Pages linking `academy-example.com, store.academy-example.com, zylvie.com`.
  - `Acme Pet Care` (Container `189484691`, Version 12): Tag 17 `gclidw` linking `petcare-example.com, store.petcare-example.com, zylvie.com`, Tag 19 `gaawe` forwarding dataLayer ecommerce events to `G-1L9JEX0TBN`.

### Fixed
- **Hyphen-Tolerant E-Commerce Tag Detection (`scripts/portfolio_gtm_audit.py`)**:
  - Tag name detection now matches `"e-commerce"` in addition to `"ecommerce"` and `"purchase"`, eliminating false-negative critical alerts for standard naming conventions like `GA4 - E-commerce Events Forwarder`.
