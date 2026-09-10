#!/usr/bin/env python3
"""Regression checks for GTM measurement-receipt boundaries."""

import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


class GtmAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.content = " ".join(SKILL.read_text(encoding="utf-8").split())

    def test_requires_explicit_parameter_mapping_readback(self):
        self.assertIn("exact event name, firing trigger conditions, and parameter-to-variable mapping", self.content)
        self.assertIn("explicit allowlist", self.content)

    def test_keeps_edge_owned_regional_policy_outside_gtm(self):
        self.assertIn("application/edge-owned regional policy", self.content)
        self.assertIn("public no-store/cache proof", self.content)

    def test_requires_a_verified_redundant_account_admin_pair(self):
        self.assertIn("check_account_admins.py", self.content)
        self.assertIn("at least two distinct account-level administrators", self.content)
        self.assertIn("tagmanager.manage.users", self.content)

    def test_uses_the_upstream_permission_api_and_verifies_activation(self):
        self.assertIn("gtm user-permissions --help", self.content)
        self.assertIn(
            "gtm user-permissions create --account-id <account-id> --email <email> --account-access admin",
            self.content,
        )
        self.assertIn("creation receipt is not proof of active access", self.content)
        self.assertIn("pending invitation", self.content)
        self.assertIn("GTM UI accepted status (or invitee authenticated access)", self.content)
        self.assertIn("separate two-admin result", self.content)

    def test_treats_pending_invitation_readback_as_a_ui_only_state(self):
        self.assertIn("human-readable success receipt even when `--output json` is requested", self.content)
        self.assertIn("do not pipe that mutation directly to `jq`", self.content)
        self.assertIn("may omit pending invitations", self.content)
        self.assertIn("verify the pending state in the GTM UI", self.content)

    def test_routes_funnel_decisions_to_the_canonical_owner(self):
        self.assertIn("canonical funnel owner (usually `docs/funnel.md`)", self.content)

    def test_requires_per_brand_paid_media_preflight(self):
        self.assertIn("every brand and advertising destination", self.content)
        direct_route = self.content.split("**Direct Google Ads conversion tag:**", 1)[1].split("**GA4 key-event import:**", 1)[0]
        self.assertIn("account-specific Google Ads Conversion ID (`AW-...`)", direct_route)
        self.assertIn("Conversion Linker", direct_route)
        self.assertIn("transaction_id", direct_route)
        self.assertIn("No Analytics destination is a prerequisite", direct_route)
        self.assertNotIn("exact GA4 property", direct_route)
        self.assertIn("GA4 audience export", self.content)
        self.assertIn("exact GA4 property/destination", self.content)
        self.assertIn("exact linked GA4 property and key-event receipt", self.content)
        self.assertIn("must not be paired with a duplicate direct Ads conversion", self.content)
        self.assertIn("not GTM mutations", self.content)

    def test_verifies_a_publish_by_comparing_versions_not_workspaces(self):
        """Locks the routing sentence, not the reader's obedience.

        The dead-workspace failure itself is enforced in code
        (`requireExistingWorkspace` + `TestSnapshotRefusesAWorkspaceThatNoLongerExists`);
        this only asserts the positive route stays documented, since an error
        message can say "not this" but not "here is the whole alternative".
        """
        self.assertIn("Publishing consumes the workspace", self.content)
        self.assertIn("creates a fresh Default Workspace with a new ID", self.content)
        self.assertIn("refuse a workspace the container no longer lists", self.content)
        self.assertIn("compare the previously live version with the new one", self.content)

    def test_warns_that_a_workspace_can_be_older_than_the_live_container(self):
        self.assertIn("older than the live container", self.content)
        self.assertIn("before treating any workspace listing as the container's current state", self.content)

    def test_confirms_the_workspace_carries_only_this_change_before_versioning(self):
        self.assertIn("workspaces status", self.content)
        self.assertIn("carries only your change", self.content)


if __name__ == "__main__":
    unittest.main()
