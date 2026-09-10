#!/usr/bin/env python3
"""Read-only GTM account-administrator redundancy readiness check."""

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from typing import Optional, Tuple


MINIMUM_ADMINS = 2
USAGE_ERROR_EXIT = 64


class UsageArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(USAGE_ERROR_EXIT, f"{self.prog}: error: {message}\n")


def write_report(report: dict[str, object]) -> None:
    print(json.dumps(report, indent=2, sort_keys=True))


def permissions_from(payload: object) -> Optional[list[Mapping[str, object]]]:
    if isinstance(payload, list):
        permissions = payload
    elif isinstance(payload, Mapping):
        permissions = payload.get("userPermission")
    else:
        return None
    if not isinstance(permissions, list) or not all(isinstance(item, Mapping) for item in permissions):
        return None
    return permissions


def administrator_identity(permission: Mapping[str, object]) -> Optional[str]:
    access = permission.get("accountAccess")
    if not isinstance(access, Mapping) or access.get("permission") != "admin":
        return None
    for key in ("emailAddress", "path", "userPermissionId"):
        value = permission.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    return ""


def assess_permissions(account_id: str, payload: object) -> Tuple[dict[str, object], int]:
    permissions = permissions_from(payload)
    if permissions is None:
        return (
            {
                "accountId": account_id,
                "adminCount": None,
                "minimumAdmins": MINIMUM_ADMINS,
                "reason": "unexpected_permission_response",
                "status": "unknown",
            },
            3,
        )

    administrators: set[str] = set()
    unresolved_admin_records = 0
    for permission in permissions:
        identity = administrator_identity(permission)
        if identity == "":
            unresolved_admin_records += 1
        elif identity is not None:
            administrators.add(identity)

    report: dict[str, object] = {
        "accountId": account_id,
        "adminCount": len(administrators),
        "minimumAdmins": MINIMUM_ADMINS,
    }
    if unresolved_admin_records:
        report.update(
            {
                "reason": "administrator_identity_unavailable",
                "status": "unknown",
            }
        )
        return report, 3
    if len(administrators) >= MINIMUM_ADMINS:
        report["status"] = "ready"
        return report, 0
    report.update(
        {
            "reason": "insufficient_distinct_account_administrators",
            "status": "needs_admin",
        }
    )
    return report, 2


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = UsageArgumentParser(
        description="Verify that a GTM account has at least two distinct account-level administrators."
    )
    parser.add_argument("--account-id", required=True, help="GTM account ID to inspect")
    parser.add_argument(
        "--gtm-agent",
        default="gtm-agent",
        help="Path to the gtm-agent executable (default: gtm-agent)",
    )
    args = parser.parse_args(argv)
    command = [
        args.gtm_agent,
        "raw",
        "--",
        "user-permissions",
        "list",
        "--account-id",
        args.account_id,
        "--output",
        "json",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError:
        write_report(
            {
                "accountId": args.account_id,
                "adminCount": None,
                "minimumAdmins": MINIMUM_ADMINS,
                "reason": "permission_audit_unavailable",
                "status": "unknown",
            }
        )
        return 3
    if result.returncode:
        write_report(
            {
                "accountId": args.account_id,
                "adminCount": None,
                "minimumAdmins": MINIMUM_ADMINS,
                "reason": "permission_audit_unavailable",
                "status": "unknown",
            }
        )
        return 3
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        write_report(
            {
                "accountId": args.account_id,
                "adminCount": None,
                "minimumAdmins": MINIMUM_ADMINS,
                "reason": "unexpected_permission_response",
                "status": "unknown",
            }
        )
        return 3
    report, exit_code = assess_permissions(args.account_id, payload)
    write_report(report)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
