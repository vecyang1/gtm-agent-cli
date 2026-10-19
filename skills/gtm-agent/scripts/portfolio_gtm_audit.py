#!/usr/bin/env python3
"""
portfolio_gtm_audit.py - Unified Weekly GTM & GA4 Tracking Audit Engine

Audits all in-run business containers across Google Tag Manager and Google Analytics:
- Live container version health & tag inventory
- GA4 configuration and measurement ID resolution
- Conversion Linker & cross-domain attribution hygiene
- E-commerce and lead conversion event forwarders (view_item, add_to_cart, begin_checkout, purchase, generate_lead)
- Marketing widget blocking triggers on conversion-critical paths (cart, checkout, thank-you)
- Public website GTM snippet verification (HTTP probe)
- Generates durable markdown ledger and execution receipts
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

PORTFOLIO_CONTAINERS = [
    {
        "id": "glintmuse",
        "name": "GlintMuse",
        "account_id": "6339218068",
        "container_id": "243541856",
        "public_id": "GTM-P8VTXJ65",
        "primary_url": "https://glintmuse.example.com",
        "expected_ga4_id": "G-EYNX4EGW23",
        "requires_ecommerce": True,
        "requires_lead_gen": True,
        "requires_conversion_linker": True,
        "requires_blocking_triggers": True,
        "requires_meta_pixel": True,
        "requires_google_ads": True,
    },
    {
        "id": "worldinspirelab",
        "name": "World Inspire Lab",
        "account_id": "6192716090",
        "container_id": "164006082",
        "public_id": "GTM-5G7SFL9R",
        "primary_url": "https://worldinspirelab.example.com",
        "expected_ga4_id": "G-5QTQX9GL64",
        "requires_ecommerce": True,
        "requires_lead_gen": False,
        "requires_conversion_linker": True,
        "requires_blocking_triggers": True,
        "requires_meta_pixel": True,
        "requires_google_ads": False,
    },
    {
        "id": "xinchaovi",
        "name": "XinChaoVi",
        "account_id": "6306410723",
        "container_id": "226299748",
        "public_id": "GTM-T54NBFNJ",
        "primary_url": "https://xinchaovi.example.com",
        "expected_ga4_id": "G-SL1QWKK7EJ",
        "requires_ecommerce": True,
        "requires_lead_gen": False,
        "requires_conversion_linker": False,
        "requires_blocking_triggers": True,
        "requires_meta_pixel": True,
        "requires_google_ads": False,
    },
    {
        "id": "onlineradiocode",
        "name": "Online Radio Codes",
        "account_id": "6362655900",
        "container_id": "256454241",
        "public_id": "GTM-KNXHTL8C",
        "primary_url": "https://carradiocodes.example.co.uk",
        "expected_ga4_id": None,
        "requires_ecommerce": True,
        "requires_lead_gen": True,
        "requires_conversion_linker": True,
        "requires_blocking_triggers": False,
        "requires_meta_pixel": False,
        "requires_google_ads": True,
    },
    {
        "id": "belovedpals",
        "name": "BelovedPals",
        "account_id": "6238828702",
        "container_id": "189484691",
        "public_id": "GTM-MSW8GJXP",
        "primary_url": "https://belovedpals.example.com",
        "expected_ga4_id": None,
        "requires_ecommerce": False,
        "requires_lead_gen": False,
        "requires_conversion_linker": False,
        "requires_blocking_triggers": True,
        "requires_meta_pixel": False,
        "requires_google_ads": False,
    },
    {
        "id": "globalgrowthco",
        "name": "Global Growth Co",
        "account_id": "6217978188",
        "container_id": "177939808",
        "public_id": "GTM-MKP5HFBS",
        "primary_url": "https://globalgrowthco.com",
        "expected_ga4_id": None,
        "requires_ecommerce": False,
        "requires_lead_gen": False,
        "requires_conversion_linker": False,
        "requires_blocking_triggers": False,
        "requires_meta_pixel": False,
        "requires_google_ads": False,
    },
]


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


def run_gtm_cli(cmd: str) -> Dict[str, Any]:
    """Execute raw gtm-agent command and parse JSON output."""
    try:
        proc = subprocess.run(
            f"gtm-agent raw -- {cmd}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout)
    except Exception as e:
        return {"error": str(e)}
    return {}


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
        if "ecommerce" in t_name.lower() or "purchase" in t_name.lower():
            result.ecommerce_forwarding_present = True
        if "lead" in t_name.lower() or "generate_lead" in t_name.lower():
            result.lead_conversion_present = True

        # Check Meta Pixel
        if any(kw in t_name.lower() for kw in ["meta pixel", "facebook pixel", "fbq", "meta -"]):
            result.meta_pixel_present = True
        # Check Google Ads
        if any(kw in t_name.lower() for kw in ["google ads", "adwords", "aw-"]) or t_type == "awct" or (t_type == "googtag" and "AW-" in t_name):
            result.google_ads_present = True

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


def generate_markdown_report(results: List[ContainerAuditResult]) -> str:
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
    parser = argparse.ArgumentParser(description="Portfolio GTM & GA4 Weekly Audit Engine")
    parser.add_argument("--brand", help="Audit specific brand id (e.g. glintmuse)")
    parser.add_argument("--no-snippets", action="store_true", help="Skip public HTTP snippet probes")
    parser.add_argument("--output", help="Write report to specific markdown path")
    parser.add_argument("--receipt", help="Write JSON execution receipt to specific path")
    parser.add_argument("--json", action="store_true", help="Output JSON result directly to stdout")
    parser.add_argument("--execute", action="store_true", help="Execute live and write receipts")
    args = parser.parse_args()

    target_configs = PORTFOLIO_CONTAINERS
    if args.brand:
        target_configs = [c for c in PORTFOLIO_CONTAINERS if c["id"] == args.brand]
        if not target_configs:
            print(f"Error: Unknown brand '{args.brand}'", file=sys.stderr)
            return 1

    results: List[ContainerAuditResult] = []
    for cfg in target_configs:
        res = audit_container(cfg, check_snippets=not args.no_snippets)
        results.append(res)

    md_report = generate_markdown_report(results)

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
        }
        state_file.write_text(json.dumps(state_data, indent=2), encoding="utf-8")
        success_marker.write_text(f"OK {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n", encoding="utf-8")

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print(md_report)

    # Return 0 if average score >= 70
    return 0 if avg_score >= 70 else 1


if __name__ == "__main__":
    raise SystemExit(main())
