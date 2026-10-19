#!/usr/bin/env python3
"""
gtm_agent.py - Python CLI front door for Google Tag Manager Agent operations

Provides a unified interface for:
- Fleet auditing & health checking across all portfolio brands
- Automated tracking self-healing & auto-build workflows
- GTM container inventory, snapshots, declarative plans, and raw operations via gtm-agent
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PORTFOLIO_AUDIT_SCRIPT = SCRIPT_DIR / "portfolio_gtm_audit.py"


def run_gtm_agent_binary(subcommand: str, extra_args: list[str]) -> int:
    """Executes the native gtm-agent binary with given arguments."""
    gtm_agent_bin = os.environ.get("GTM_AGENT_BIN") or "gtm-agent"
    cmd = [gtm_agent_bin, subcommand] + extra_args
    try:
        proc = subprocess.run(cmd)
        return proc.returncode
    except FileNotFoundError:
        print(f"Error: Could not locate '{gtm_agent_bin}'. Ensure it is on your PATH or set GTM_AGENT_BIN.", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="gtm_agent.py",
        description="Unified Google Tag Manager Agent CLI & Self-Healing Control Plane",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. audit subcommand
    audit_parser = subparsers.add_parser(
        "audit",
        help="Audit GTM & GA4 tracking compliance across portfolio brands",
    )
    audit_parser.add_argument("--brand", help="Target brand id (e.g. glintmuse, belovedpals)")
    audit_parser.add_argument("--no-snippets", action="store_true", help="Skip public HTTP snippet probes")
    audit_parser.add_argument("--json", action="store_true", help="Output JSON results to stdout")
    audit_parser.add_argument("--execute", action="store_true", help="Execute live mutations and write receipts")
    audit_parser.add_argument("--output", help="Write report to specific markdown path")
    audit_parser.add_argument("--receipt", help="Write JSON execution receipt to specific path")

    # 2. autobuild subcommand
    autobuild_parser = subparsers.add_parser(
        "autobuild",
        help="Auto-build and self-heal missing conversion events, pixels, and tracking tags",
    )
    autobuild_parser.add_argument("--brand", help="Target brand id (e.g. glintmuse, belovedpals)")
    autobuild_parser.add_argument("--execute", action="store_true", help="Execute mutations (default: dry-run)")
    autobuild_parser.add_argument("--allow-publish", action="store_true", help="Publish newly created version")
    autobuild_parser.add_argument("--confirm", help="Container ID confirmation required for publishing (or 'all')")
    autobuild_parser.add_argument("--allow-legacy-init", action="store_true", help="Authorize first-time container init")
    autobuild_parser.add_argument("--force-workspace", action="store_true", help="Allow mutating dirty workspace")
    autobuild_parser.add_argument("--no-snippets", action="store_true", help="Skip public HTTP snippet probes")
    autobuild_parser.add_argument("--json", action="store_true", help="Output JSON results to stdout")
    autobuild_parser.add_argument("--backup-dir", help="Directory for rollback backups")

    # 3. doctor subcommand
    doctor_parser = subparsers.add_parser("doctor", help="Check upstream gtm, auth, and config state")
    doctor_parser.add_argument("--json", action="store_true", help="Output JSON")

    # 4. inventory subcommand
    inv_parser = subparsers.add_parser("inventory", help="Collect stable JSON inventory from GTM")
    inv_parser.add_argument("--account-id", required=True, help="GTM Account ID")
    inv_parser.add_argument("--container-id", required=True, help="GTM Container ID")
    inv_parser.add_argument("--workspace-id", help="GTM Workspace ID")
    inv_parser.add_argument("--json", action="store_true", help="Output JSON")

    # 5. snapshot subcommand
    snap_parser = subparsers.add_parser("snapshot", help="Write timestamped GTM inventory snapshot")
    snap_parser.add_argument("--account-id", required=True, help="GTM Account ID")
    snap_parser.add_argument("--container-id", required=True, help="GTM Container ID")
    snap_parser.add_argument("--workspace-id", help="GTM Workspace ID")
    snap_parser.add_argument("--out", help="Output file path")
    snap_parser.add_argument("--json", action="store_true", help="Output JSON")

    # 6. diff subcommand
    diff_parser = subparsers.add_parser("diff", help="Compare two GTM snapshots")
    diff_parser.add_argument("before", help="Path to before snapshot JSON")
    diff_parser.add_argument("after", help="Path to after snapshot JSON")
    diff_parser.add_argument("--json", action="store_true", help="Output JSON")

    # 7. raw subcommand
    raw_parser = subparsers.add_parser("raw", help="Pass through raw command to upstream gtm CLI")
    raw_parser.add_argument("--allow-mutation", action="store_true", help="Permit mutating commands")
    raw_parser.add_argument("--allow-publish", action="store_true", help="Permit version publishing")
    raw_parser.add_argument("--confirm", help="Container ID confirmation required for publish")
    raw_parser.add_argument("raw_args", nargs=argparse.REMAINDER, help="Arguments passed to upstream gtm")

    if len(sys.argv) == 1:
        parser.print_help()
        return 0

    args, unknown = parser.parse_known_args()

    if args.command == "audit":
        audit_args = [sys.executable, str(PORTFOLIO_AUDIT_SCRIPT)]
        if args.brand:
            audit_args.extend(["--brand", args.brand])
        if args.no_snippets:
            audit_args.append("--no-snippets")
        if args.json:
            audit_args.append("--json")
        if args.execute:
            audit_args.append("--execute")
        if args.output:
            audit_args.extend(["--output", args.output])
        if args.receipt:
            audit_args.extend(["--receipt", args.receipt])
        audit_args.extend(unknown)
        return subprocess.run(audit_args).returncode

    elif args.command == "autobuild":
        build_args = [sys.executable, str(PORTFOLIO_AUDIT_SCRIPT), "--auto-build"]
        if args.brand:
            build_args.extend(["--brand", args.brand])
        if args.execute:
            build_args.append("--execute")
        if args.allow_publish:
            build_args.append("--allow-publish")
        if args.confirm:
            build_args.extend(["--confirm", args.confirm])
        if args.allow_legacy_init:
            build_args.append("--allow-legacy-init")
        if args.force_workspace:
            build_args.append("--force-workspace")
        if args.no_snippets:
            build_args.append("--no-snippets")
        if args.json:
            build_args.append("--json")
        if args.backup_dir:
            build_args.extend(["--backup-dir", args.backup_dir])
        build_args.extend(unknown)
        return subprocess.run(build_args).returncode

    elif args.command in ("doctor", "inventory", "snapshot", "diff"):
        return run_gtm_agent_binary(args.command, sys.argv[2:])

    elif args.command == "raw":
        raw_cmd_args = []
        if args.allow_mutation:
            raw_cmd_args.append("--allow-mutation")
        if args.allow_publish:
            raw_cmd_args.append("--allow-publish")
        if args.confirm:
            raw_cmd_args.extend(["--confirm", args.confirm])
        raw_cmd_args.append("--")
        raw_cmd_args.extend(args.raw_args)
        return run_gtm_agent_binary("raw", raw_cmd_args)

    else:
        # Fallback to direct gtm-agent command
        return run_gtm_agent_binary(sys.argv[1], sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
