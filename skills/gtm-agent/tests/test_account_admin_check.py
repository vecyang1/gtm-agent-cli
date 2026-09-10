#!/usr/bin/env python3
"""Behavioral tests for the GTM account-administrator readiness check."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "check_account_admins.py"


class AccountAdminCheckTests(unittest.TestCase):
    def run_check(self, permissions):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "fake-gtm-agent"
            expected = [
                "raw",
                "--",
                "user-permissions",
                "list",
                "--account-id",
                "123",
                "--output",
                "json",
            ]
            fake.write_text(
                "#!" + sys.executable + "\n"
                "import json, sys\n"
                f"expected = {expected!r}\n"
                "if sys.argv[1:] != expected:\n"
                "    raise SystemExit('unexpected command: ' + repr(sys.argv[1:]))\n"
                f"print(json.dumps({permissions!r}))\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--gtm-agent",
                    str(fake),
                    "--account-id",
                    "123",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertTrue(result.stdout.strip(), result.stderr)
            return result

    def test_passes_only_with_two_distinct_account_administrators(self):
        result = self.run_check(
            {
                "userPermission": [
                    {"emailAddress": "owner@example.com", "accountAccess": {"permission": "admin"}},
                    {"emailAddress": "backup@example.com", "accountAccess": {"permission": "admin"}},
                    {"emailAddress": "publisher@example.com", "accountAccess": {"permission": "user"}},
                ]
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["adminCount"], 2)
        self.assertEqual(report["minimumAdmins"], 2)
        self.assertNotIn("emailAddress", result.stdout)

    def test_fails_when_the_same_admin_is_listed_twice_or_only_container_publish_exists(self):
        result = self.run_check(
            {
                "userPermission": [
                    {"emailAddress": "owner@example.com", "accountAccess": {"permission": "admin"}},
                    {"emailAddress": "OWNER@example.com", "accountAccess": {"permission": "admin"}},
                    {
                        "emailAddress": "publisher@example.com",
                        "accountAccess": {"permission": "user"},
                        "containerAccess": [{"containerId": "456", "permission": "publish"}],
                    },
                ]
            }
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "needs_admin")
        self.assertEqual(report["adminCount"], 1)
        self.assertEqual(report["minimumAdmins"], 2)

    def test_invalid_usage_does_not_collide_with_the_needs_admin_exit_code(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 64, result.stderr)
        self.assertFalse(result.stdout)


if __name__ == "__main__":
    unittest.main()
