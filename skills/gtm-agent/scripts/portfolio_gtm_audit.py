#!/usr/bin/env python3
"""
portfolio_gtm_audit.py - Unified Weekly GTM & GA4 Tracking Audit & Auto-Build Engine

Audits and automatically repairs all in-run business containers across Google Tag Manager and Google Analytics:
- Live container version health & tag inventory
- GA4 configuration and measurement ID resolution
- Conversion Linker & cross-domain attribution hygiene
- E-commerce and lead conversion event forwarders (view_item, add_to_cart, begin_checkout, purchase, generate_lead)
- Marketing widget blocking triggers on conversion-critical paths (cart, checkout, thank-you)
- Public website GTM snippet verification (HTTP probe)
- Self-healing Auto-Build workflow with safety gates, idempotency checks, rollback backups, and version publishing
- Generates durable markdown ledger and execution receipts
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_BACKUP_DIR = SKILL_DIR.parent / "backups"

# Import auto-build engine components
try:
    from gtm_autobuild import (
        AutoBuildItem,
        AutoBuildOptions,
        ContainerAutoBuildPlan,
        GtmAutoBuilder,
        GtmSafetyGuard,
        SafetyGateError,
    )
except ImportError:
    # If run directly as script
    sys.path.insert(0, str(SCRIPT_DIR))
    from gtm_autobuild import (
        AutoBuildItem,
        AutoBuildOptions,
        ContainerAutoBuildPlan,
        GtmAutoBuilder,
        GtmSafetyGuard,
        SafetyGateError,
    )

def _load_portfolio_containers() -> List[Dict[str, Any]]:
    config_env = os.environ.get("GTM_PORTFOLIO_CONFIG")
    candidates = [
        Path(config_env) if config_env else None,
        SKILL_DIR / "config" / "containers.local.json",
        SCRIPT_DIR / "containers.local.json",
        SKILL_DIR / "config" / "containers.json",
    ]
    for c in candidates:
        if c and c.exists():
            try:
                with open(c, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        return data
            except Exception:
                pass

    return [
        {
            "id": "sample-ecommerce",
            "name": "Sample E-commerce",
            "account_id": "123456789",
            "container_id": "987654321",
            "public_id": "GTM-SAMPLE01",
            "primary_url": "https://store.example.com",
            "expected_ga4_id": "G-SAMPLE01",
            "expected_google_ads_id": "AW-SAMPLE01",
            "expected_meta_pixel_id": "SAMPLE01",
            "requires_ecommerce": True,
            "requires_lead_gen": True,
            "requires_conversion_linker": True,
            "requires_blocking_triggers": True,
            "requires_meta_pixel": True,
            "requires_google_ads": True,
        },
        {
            "id": "sample-leads",
            "name": "Sample Lead Gen",
            "account_id": "123456789",
            "container_id": "987654322",
            "public_id": "GTM-SAMPLE02",
            "primary_url": "https://leads.example.com",
            "expected_ga4_id": "G-SAMPLE02",
            "expected_google_ads_id": "AW-SAMPLE02",
            "expected_meta_pixel_id": "SAMPLE02",
            "requires_ecommerce": False,
            "requires_lead_gen": True,
            "requires_conversion_linker": True,
            "requires_blocking_triggers": False,
            "requires_meta_pixel": False,
            "requires_google_ads": False,
        },
    ]

PORTFOLIO_CONTAINERS = _load_portfolio_containers()

# Web Supply Chain & External Script Watchlists
HIJACKED_OR_DEPRECATED_DOMAINS: Set[str] = {
    "cdn.taku-app.com",
    "taku-app.com",
}

APPROVED_VENDOR_DOMAINS: Set[str] = {
    "googletagmanager.com",
    "google-analytics.com",
    "googleadservices.com",
    "google.com",
    "clarity.ms",
    "connect.facebook.net",
    "facebook.com",
    "cdn.taku.cool",
    "scripts.claspo.io",
    "cdnjs.cloudflare.com",
    "plugin.nytsys.com",
    "plugin-api-4.nytroseo.com",
    "resources-app.encharge.io",
    "visitor.leadsourcing.co",
    "widget.cxgenie.ai",
    "app.visitortracking.com",
    "zylvie.com",
    "analytics.tiktok.com",
    "ct.pinterest.com",
    "snap.licdn.com",
    "licdn.com",
    "app.chaport.com",
    "cdn.growify.ai",
    "cdn.nuwtonic.com",
    "worldinspirelab.com",
    "glintmuse.com",
    "belovedpals.com",
    "globalgrowthco.com",
    "xinchaovi.com",
}


def extract_domains_from_html(html_str: str) -> List[str]:
    """Extracts all external hostnames from script tags and URLs in HTML/JS snippet."""
    domains = set()
    # 1. <script src="...">
    src_matches = re.findall(r'<script[^>]+src=[\'"]([^\'"]+)[\'"]', html_str, re.IGNORECASE)
    for src in src_matches:
        src = src.strip()
        if src.startswith("//"):
            src = "https:" + src
        try:
            parsed = urllib.parse.urlparse(src)
            if parsed.netloc:
                domains.add(parsed.netloc.lower())
        except Exception:
            pass

    # 2. String literal URLs in inline JS (e.g. .src = "https://...")
    url_matches = re.findall(r'https?://[a-zA-Z0-9\-\.]+(?::[0-9]+)?', html_str)
    for u in url_matches:
        try:
            parsed = urllib.parse.urlparse(u)
            if parsed.netloc:
                domains.add(parsed.netloc.lower())
        except Exception:
            pass

    # 3. Protocol-relative URLs (//visitor.leadsourcing.co/...)
    proto_rel = re.findall(r'//([a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,})', html_str)
    for h in proto_rel:
        domains.add(h.lower())

    return sorted(list(domains))


@dataclass
class ContainerAuditResult:
    brand_id: str
    brand_name: str
    account_id: str
    container_id: str
    public_id: str
    primary_url: str
    live_version_id: Optional[str] = None
    live_version_name: Optional[str] = None
    tag_count: int = 0
    trigger_count: int = 0
    variable_count: int = 0
    ga4_configured: bool = False
    google_ads_present: bool = False
    meta_pixel_present: bool = False
    conversion_linker_present: bool = False
    ecommerce_forwarding_present: bool = False
    lead_conversion_present: bool = False
    blocking_triggers_present: bool = False
    snippet_detected_live: bool = False
    score: int = 100
    issues: List[str] = field(default_factory=list)
    tags_summary: List[Dict[str, Any]] = field(default_factory=list)
    third_party_scripts: List[Dict[str, Any]] = field(default_factory=list)
    hijacked_domains_found: List[str] = field(default_factory=list)


def safe_json_loads(text: str) -> Any:
    """Robust JSON extraction handling trailing/leading text notes from CLI output."""
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start_obj = text.find("{")
        end_obj = text.rfind("}")
        start_arr = text.find("[")
        end_arr = text.rfind("]")

        candidates = []
        if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            candidates.append(text[start_obj : end_obj + 1])
        if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
            candidates.append(text[start_arr : end_arr + 1])

        for c in candidates:
            try:
                return json.loads(c)
            except json.JSONDecodeError:
                continue
        return {"raw_text": text}


def run_gtm_cli(
    cmd: str,
    allow_mutation: bool = False,
    allow_publish: bool = False,
    confirm: Optional[str] = None,
    timeout: int = 45,
    retries: int = 2,
) -> Dict[str, Any]:
    """Execute raw gtm-agent command and parse JSON output with safety flags and transient retry."""
    import time

    flags = []
    if allow_mutation:
        flags.append("--allow-mutation")
    if allow_publish:
        flags.append("--allow-publish")
    if confirm:
        flags.extend(["--confirm", confirm])
    flag_str = (" " + " ".join(flags)) if flags else ""
    full_cmd = f"gtm-agent raw{flag_str} -- {cmd}"

    last_error: Dict[str, Any] = {}
    attempts = retries if not allow_mutation else 0

    for attempt in range(attempts + 1):
        try:
            proc = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.stdout.strip():
                parsed = safe_json_loads(proc.stdout)
                if isinstance(parsed, (dict, list)):
                    if isinstance(parsed, dict) and "error" in parsed:
                        last_error = parsed
                        if attempt < attempts:
                            time.sleep(1.0 * (attempt + 1))
                            continue
                    return parsed
            if proc.returncode != 0:
                err_msg = proc.stderr.strip() or f"Command failed with exit code {proc.returncode}"
                last_error = {"error": err_msg}
                if attempt < attempts:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                return last_error
        except Exception as e:
            last_error = {"error": str(e)}
            if attempt < attempts:
                time.sleep(1.0 * (attempt + 1))
                continue
            return last_error

    return last_error or {}


def probe_public_snippet(url: str, public_id: str) -> bool:
    """Verifies that the target website HTML contains the public GTM container snippet."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return public_id in body
    except Exception:
        return False


def audit_container(config: Dict[str, Any], check_snippets: bool = True) -> ContainerAuditResult:
    brand_id = config["id"]
    brand_name = config["name"]
    acc_id = config["account_id"]
    cont_id = config["container_id"]
    public_id = config["public_id"]
    url = config["primary_url"]

    result = ContainerAuditResult(
        brand_id=brand_id,
        brand_name=brand_name,
        account_id=acc_id,
        container_id=cont_id,
        public_id=public_id,
        primary_url=url,
    )

    # 1. Fetch Live Version
    v_data = run_gtm_cli(f"versions live --account-id {acc_id} --container-id {cont_id} --output json")
    if "error" in v_data or not v_data.get("containerVersionId"):
        result.issues.append(f"CRITICAL: Failed to fetch live version: {v_data.get('error', 'empty payload')}")
        result.score = 0
        return result

    result.live_version_id = str(v_data.get("containerVersionId"))
    result.live_version_name = v_data.get("name") or "Unlabeled"
    tags = v_data.get("tag", [])
    triggers = v_data.get("trigger", [])
    variables = v_data.get("variable", [])

    result.tag_count = len(tags)
    result.trigger_count = len(triggers)
    result.variable_count = len(variables)

    # 2. Inspect Tags
    tag_names = [t.get("name", "").lower() for t in tags]
    tag_types = [t.get("type", "") for t in tags]

    # Check GA4 Config Tag
    for t in tags:
        t_type = t.get("type", "")
        t_name = t.get("name", "")
        result.tags_summary.append({
            "id": t.get("tagId"),
            "name": t_name,
            "type": t_type,
            "firing": t.get("firingTriggerId", []),
            "blocking": t.get("blockingTriggerId", []),
        })

        if t_type == "googtag" or "ga4" in t_name.lower():
            result.ga4_configured = True
        if t_type == "gclidw":
            result.conversion_linker_present = True
        if "ecommerce" in t_name.lower() or "e-commerce" in t_name.lower() or "purchase" in t_name.lower():
            result.ecommerce_forwarding_present = True
        if "lead" in t_name.lower() or "generate_lead" in t_name.lower():
            result.lead_conversion_present = True

        # Check Meta Pixel
        if any(kw in t_name.lower() for kw in ["meta pixel", "facebook pixel", "fbq", "meta -", "meta bl", "meta "]):
            result.meta_pixel_present = True
        elif any("fbq(" in p.get("value", "") for p in t.get("parameter", [])):
            result.meta_pixel_present = True

        # Check Google Ads
        if any(kw in t_name.lower() for kw in ["google ads", "adwords", "aw-"]) or t_type == "awct" or (t_type == "googtag" and "AW-" in t_name):
            result.google_ads_present = True

        # Check Third-Party Script Domains & Supply Chain Safety
        extracted_domains = []
        if t_type == "html":
            for p in t.get("parameter", []):
                if p.get("key") == "html" and p.get("value"):
                    extracted_domains = extract_domains_from_html(p.get("value"))
        elif t_type == "cvt_MQDKZ":
            extracted_domains = ["clarity.ms"]
        elif t_type == "bzi":
            extracted_domains = ["snap.licdn.com"]
        elif t_type in ("googtag", "gaawe", "gclidw", "awct"):
            extracted_domains = ["googletagmanager.com"]

        if extracted_domains:
            # Check for hijacked / deprecated domains
            hijacked_hits = [d for d in extracted_domains if any(bad in d for bad in HIJACKED_OR_DEPRECATED_DOMAINS)]
            if hijacked_hits:
                verdict = "CRITICAL_HIJACKED"
                for bad in hijacked_hits:
                    result.hijacked_domains_found.append(f"{bad} in tag '{t_name}'")
                    result.issues.append(f"CRITICAL: Hijacked/abandoned domain detected in tag '{t_name}': {bad}!")
                result.score -= 50
            elif all(any(d == app or d.endswith("." + app) for app in APPROVED_VENDOR_DOMAINS) for d in extracted_domains):
                verdict = "SAFE_PARTNER"
            else:
                verdict = "UNVERIFIED"
                unverified = [d for d in extracted_domains if not any(d == app or d.endswith("." + app) for app in APPROVED_VENDOR_DOMAINS)]
                result.issues.append(f"WARN: Unverified external domain(s) in tag '{t_name}': {', '.join(unverified)}")

            result.third_party_scripts.append({
                "tag_id": str(t.get("tagId", "")),
                "name": t_name,
                "type": t_type,
                "paused": bool(t.get("paused", False)),
                "domains": extracted_domains,
                "verdict": verdict,
            })

    # Check Blocking Triggers
    blocking_triggers = [
        tr for tr in triggers
        if any(kw in tr.get("name", "").lower() for kw in ["blocking", "cart", "checkout", "thank", "receipt", "quiz"])
    ]
    if blocking_triggers:
        result.blocking_triggers_present = True

    # 3. Compliance & Scoring Checks
    if not result.ga4_configured:
        result.issues.append("CRITICAL: No Google Tag / GA4 configuration tag found.")
        result.score -= 40

    if config.get("requires_conversion_linker") and not result.conversion_linker_present:
        result.issues.append("WARN: Conversion Linker (gclidw) missing for paid advertising attribution.")
        result.score -= 15

    if config.get("requires_ecommerce") and not result.ecommerce_forwarding_present:
        result.issues.append("CRITICAL: Transactional brand missing e-commerce conversion forwarding tag.")
        result.score -= 25

    if config.get("requires_lead_gen") and not result.lead_conversion_present:
        result.issues.append("WARN: Lead generation conversion tag (generate_lead) missing.")
        result.score -= 15

    if config.get("requires_meta_pixel") and not result.meta_pixel_present:
        result.issues.append("WARN: Meta Pixel tag missing for social ad measurement.")
        result.score -= 10

    if config.get("requires_google_ads") and not result.google_ads_present:
        result.issues.append("WARN: Google Ads conversion / base tag missing.")
        result.score -= 15

    if config.get("requires_blocking_triggers") and not result.blocking_triggers_present:
        result.issues.append("WARN: Conversion-critical blocking triggers (cart, checkout, thank-you) missing.")
        result.score -= 10

    # 4. Snippet Probe
    if check_snippets and url:
        is_live = probe_public_snippet(url, public_id)
        result.snippet_detected_live = is_live
        if not is_live:
            result.issues.append(f"WARN: Public snippet probe failed to locate {public_id} on {url}.")
            result.score -= 10
    else:
        result.snippet_detected_live = True

    result.score = max(0, result.score)
    return result


def generate_markdown_report(
    results: List[ContainerAuditResult],
    auto_build_plans: Optional[List[ContainerAutoBuildPlan]] = None,
) -> str:
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    date_str = datetime.date.today().isoformat()

    total_brands = len(results)
    healthy_brands = sum(1 for r in results if r.score >= 80)
    avg_score = round(sum(r.score for r in results) / total_brands, 1) if total_brands else 0

    lines = [
        f"# Portfolio GTM & GA4 Tracking Audit Ledger",
        f"",
        f"- **Audit Date:** `{date_str}` ({now_str})",
        f"- **Audited Brands:** {total_brands} | **Healthy (>=80%):** {healthy_brands} | **Avg Portfolio Score:** {avg_score}%",
        f"- **Automation Mode:** Weekly Agentic Cadence (`CAD-20261019-portfolio-gtm-ga4-weekly-audit`)",
        f"",
        f"## Executive Portfolio Matrix",
        f"",
        f"| Brand | Container ID | Live Ver | Tags / Triggers | GA4 | Google Ads | Meta Pixel | Linker | E-Comm | Leads | Blocking | Snippet | Score | Status |",
        f"|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        status_icon = "🟢 PASS" if r.score >= 85 else ("🟡 WARN" if r.score >= 70 else "🔴 ALERT")
        ga4_icon = "✅" if r.ga4_configured else "❌"
        cfg_match = next((c for c in PORTFOLIO_CONTAINERS if c["id"] == r.brand_id), {})
        gads_icon = "✅" if r.google_ads_present else ("⚪" if not cfg_match.get("requires_google_ads") else "❌")
        meta_icon = "✅" if r.meta_pixel_present else ("⚪" if not cfg_match.get("requires_meta_pixel") else "❌")
        linker_icon = "✅" if r.conversion_linker_present else "⚪"
        ecomm_icon = "✅" if r.ecommerce_forwarding_present else "⚪"
        leads_icon = "✅" if r.lead_conversion_present else "⚪"
        block_icon = "✅" if r.blocking_triggers_present else "⚪"
        snip_icon = "✅" if r.snippet_detected_live else "⚠️"

        lines.append(
            f"| **{r.brand_name}** | `{r.public_id}` | v{r.live_version_id or '?'} | {r.tag_count} / {r.trigger_count} | {ga4_icon} | {gads_icon} | {meta_icon} | {linker_icon} | {ecomm_icon} | {leads_icon} | {block_icon} | {snip_icon} | **{r.score}%** | {status_icon} |"
        )

    # Auto-Build Execution Ledger if plans were run
    if auto_build_plans:
        lines.extend([
            f"",
            f"## Automated Self-Healing & Auto-Build Ledger",
            f"",
            f"| Brand | Container ID | Status | Actions Planned / Applied | Version Created | Published | Rollback Backup | Score Change |",
            f"|---|---|---|---|---|---|---|---|",
        ])
        for p in auto_build_plans:
            act_names = ", ".join(a.name for a in p.actions) or "None"
            ver_text = f"v{p.created_version_id}" if p.created_version_id else "N/A"
            pub_text = "✅ Yes" if p.status == "published" else ("⚪ Dry Run" if p.status == "dry_run" else "❌ No")
            bak_text = f"`{Path(p.backup_file).name}`" if p.backup_file else "N/A"
            score_change = f"{p.post_audit_score}%" if p.post_audit_score is not None else "Pending"
            lines.append(
                f"| **{p.brand_name}** | `{p.public_id}` | `{p.status.upper()}` | {act_names} | {ver_text} | {pub_text} | {bak_text} | {score_change} |"
            )

    # Web Supply Chain & Third-Party Script Security Section
    lines.extend([
        f"",
        f"## Web Supply Chain & External Script Security Audit (供应链与第三方脚本安全排查)",
        f"",
        f"| Brand | Tag Name | Type | Status | Extracted Domains | Security Verdict |",
        f"|---|---|---|---|---|---|",
    ])
    total_scripts = 0
    total_hijacked = 0
    for r in results:
        for s in r.third_party_scripts:
            total_scripts += 1
            status_badge = "⏸️ PAUSED" if s.get("paused") else "▶️ ACTIVE"
            if s.get("verdict") == "CRITICAL_HIJACKED":
                total_hijacked += 1
                v_badge = "🔴 CRITICAL_HIJACKED"
            elif s.get("verdict") == "SAFE_PARTNER":
                v_badge = "🟢 SAFE_PARTNER"
            else:
                v_badge = "🟡 UNVERIFIED"
            domains_str = ", ".join(f"`{d}`" for d in s.get("domains", [])) or "None"
            lines.append(
                f"| **{r.brand_name}** | {s.get('name')} | `{s.get('type')}` | {status_badge} | {domains_str} | {v_badge} |"
            )

    if total_hijacked == 0:
        lines.append(f"\n> 🛡️ **Supply Chain Safety Gate**: 0 hijacked/deprecated domains found across {total_scripts} tracked script configurations.\n")
    else:
        lines.append(f"\n> ⚠️ **Supply Chain Alert**: Found {total_hijacked} hijacked/deprecated domain instances requiring immediate remediation!\n")

    lines.extend([
        f"",
        f"## Actionable Diagnostics & Findings",
        f"",
    ])

    issue_count = 0
    for r in results:
        if r.issues:
            lines.append(f"### {r.brand_name} (`{r.public_id}`)")
            for issue in r.issues:
                issue_count += 1
                lines.append(f"- {issue}")
            lines.append("")

    if issue_count == 0:
        lines.append("🎉 All portfolio containers passed validation with zero critical drift or missing conversion gates.\n")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Portfolio GTM & GA4 Weekly Audit & Self-Healing Engine")
    parser.add_argument("--brand", help="Audit specific brand id (e.g. glintmuse, belovedpals)")
    parser.add_argument("--no-snippets", action="store_true", help="Skip public HTTP snippet probes")
    parser.add_argument("--output", help="Write report to specific markdown path")
    parser.add_argument("--receipt", help="Write JSON execution receipt to specific path")
    parser.add_argument("--json", action="store_true", help="Output JSON result directly to stdout")
    parser.add_argument("--execute", action="store_true", help="Execute live mutations and write receipts")
    
    # Self-Healing & Auto-Build Flags
    parser.add_argument(
        "--auto-build",
        "--auto-fix",
        dest="auto_build",
        action="store_true",
        help="Auto-build missing conversion events, pixels, and tracking tags",
    )
    parser.add_argument(
        "--allow-publish",
        action="store_true",
        help="Allow publishing newly created container versions live",
    )
    parser.add_argument(
        "--confirm",
        help="Container ID confirmation required for publishing (or 'all')",
    )
    parser.add_argument(
        "--allow-legacy-init",
        action="store_true",
        help="Allow initializing uninitialized or legacy containers",
    )
    parser.add_argument(
        "--force-workspace",
        action="store_true",
        help="Allow using a workspace even if it has pending uncommitted changes",
    )
    parser.add_argument(
        "--backup-dir",
        help="Directory to save rollback backups (default: backups)",
    )

    args = parser.parse_args()

    target_configs = PORTFOLIO_CONTAINERS
    if args.brand:
        target_configs = [c for c in PORTFOLIO_CONTAINERS if c["id"] == args.brand]
        if not target_configs:
            print(f"Error: Unknown brand '{args.brand}'", file=sys.stderr)
            return 1

    # Phase 1: Run Initial Fleet Audit
    results: List[ContainerAuditResult] = []
    for cfg in target_configs:
        res = audit_container(cfg, check_snippets=not args.no_snippets)
        results.append(res)

    auto_build_plans: List[ContainerAutoBuildPlan] = []

    # Phase 2: If --auto-build / --auto-fix requested
    if args.auto_build:
        builder = GtmAutoBuilder(run_gtm_cli)
        backup_dir = Path(args.backup_dir) if args.backup_dir else DEFAULT_BACKUP_DIR
        opts = AutoBuildOptions(
            execute=args.execute,
            allow_publish=args.allow_publish,
            confirm=args.confirm,
            allow_legacy_init=args.allow_legacy_init,
            force_workspace=args.force_workspace,
            backup_dir=backup_dir,
        )

        for cfg in target_configs:
            res = next(r for r in results if r.brand_id == cfg["id"])
            # If container has issues or score < 100
            if res.score < 100 or res.issues:
                v_data = run_gtm_cli(f"versions live --account-id {cfg['account_id']} --container-id {cfg['container_id']} --output json")
                plan = builder.synthesize_plan(cfg, res, v_data)
                if plan.actions:
                    auto_build_plans.append(plan)
                    if not args.execute:
                        # Dry run plan
                        builder.execute_plan(plan, cfg, v_data, opts)
                    else:
                        print(f"🔧 Auto-building tracking for {cfg['name']} ({cfg['public_id']})...", file=sys.stderr)
                        try:
                            executed_plan = builder.execute_plan(plan, cfg, v_data, opts)
                            if executed_plan.status == "published":
                                # Post-publish re-audit to verify live status
                                re_audit = audit_container(cfg, check_snippets=not args.no_snippets)
                                executed_plan.post_audit_score = re_audit.score
                                # Update result in matrix
                                idx = next(i for i, r in enumerate(results) if r.brand_id == cfg["id"])
                                results[idx] = re_audit
                                print(f"✅ Successfully published {cfg['name']} v{executed_plan.created_version_id}! Score: {res.score}% -> {re_audit.score}%", file=sys.stderr)
                            elif executed_plan.status == "version_created_unpublished":
                                print(f"ℹ️ Created version {executed_plan.created_version_id} for {cfg['name']} (unpublished). Use --allow-publish --confirm {cfg['container_id']} to go live.", file=sys.stderr)
                            elif executed_plan.error:
                                print(f"⚠️ Warning for {cfg['name']}: {executed_plan.error}", file=sys.stderr)
                        except Exception as e:
                            plan.status = "error"
                            plan.error = str(e)
                            print(f"❌ Auto-build failed for {cfg['name']}: {e}", file=sys.stderr)

    md_report = generate_markdown_report(results, auto_build_plans=auto_build_plans if auto_build_plans else None)

    # Determine default paths
    date_str = datetime.date.today().isoformat()
    reports_dir = SKILL_DIR / "reports" / "runs"
    reports_dir.mkdir(parents=True, exist_ok=True)

    out_path = Path(args.output) if args.output else (reports_dir / f"{date_str}-gtm-portfolio-audit.md")
    receipt_path = Path(args.receipt) if args.receipt else (reports_dir / f"{date_str}-gtm-portfolio-audit.json")

    avg_score = sum(r.score for r in results) / len(results) if results else 0

    if args.execute or args.output or args.receipt:
        out_path.write_text(md_report, encoding="utf-8")
        receipt_data = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "date": date_str,
            "total_brands": len(results),
            "healthy_count": sum(1 for r in results if r.score >= 80),
            "avg_score": round(avg_score, 1),
            "results": [asdict(r) for r in results],
            "auto_build_plans": [asdict(p) for p in auto_build_plans] if auto_build_plans else [],
        }
        receipt_path.write_text(json.dumps(receipt_data, indent=2), encoding="utf-8")

        # Also touch durable output owner: reports/runs/gtm-portfolio-audit.md
        ledger_path = reports_dir / "gtm-portfolio-audit.md"
        ledger_path.write_text(md_report, encoding="utf-8")

        # Write cadence checkpoint state and success marker
        cadence_id = "CAD-20261019-portfolio-gtm-ga4-weekly-audit"
        cadence_run_dir = SKILL_DIR / ".run" / "cadence" / cadence_id
        cadence_run_dir.mkdir(parents=True, exist_ok=True)
        state_file = cadence_run_dir / "state.json"
        success_marker = cadence_run_dir / f"{date_str}.success"

        state_data = {
            "cadence_id": cadence_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "date": date_str,
            "total_brands": len(results),
            "healthy_count": sum(1 for r in results if r.score >= 80),
            "avg_score": round(avg_score, 1),
            "status": "success" if avg_score >= 70 else "degraded",
            "auto_build_count": len([p for p in auto_build_plans if p.status == "published"]),
        }
        state_file.write_text(json.dumps(state_data, indent=2), encoding="utf-8")
        success_marker.write_text(f"OK {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n", encoding="utf-8")

    if args.json:
        output_payload = {
            "results": [asdict(r) for r in results],
            "auto_build_plans": [asdict(p) for p in auto_build_plans],
        }
        print(json.dumps(output_payload, indent=2))
    else:
        print(md_report)

    # Return 0 if average score >= 70
    return 0 if avg_score >= 70 else 1


if __name__ == "__main__":
    raise SystemExit(main())
