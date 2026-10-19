#!/usr/bin/env python3
"""
test_autobuild.py - Comprehensive Unit & Integration tests for GTM Auto-Build & Self-Healing Engine
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

import sys
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from gtm_autobuild import (
    AutoBuildItem,
    AutoBuildOptions,
    ContainerAutoBuildPlan,
    GtmAutoBuilder,
    GtmSafetyGuard,
    SafetyGateError,
)
from portfolio_gtm_audit import ContainerAuditResult


class GtmAutoBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.config = {
            "id": "testbrand",
            "name": "Test Brand",
            "account_id": "111111",
            "container_id": "222222",
            "public_id": "GTM-TEST999",
            "primary_url": "https://testbrand.com",
            "expected_ga4_id": "G-TESTGA4ID",
            "expected_google_ads_id": "AW-999999999",
            "expected_meta_pixel_id": "123456789012345",
            "requires_ecommerce": True,
            "requires_lead_gen": True,
            "requires_conversion_linker": True,
            "requires_blocking_triggers": True,
            "requires_meta_pixel": True,
            "requires_google_ads": True,
        }
        self.audit_result = ContainerAuditResult(
            brand_id="testbrand",
            brand_name="Test Brand",
            account_id="111111",
            container_id="222222",
            public_id="GTM-TEST999",
            primary_url="https://testbrand.com",
            live_version_id="1",
            live_version_name="v1",
            ga4_configured=False,
            conversion_linker_present=False,
            ecommerce_forwarding_present=False,
            lead_conversion_present=False,
            meta_pixel_present=False,
            google_ads_present=False,
            blocking_triggers_present=False,
            score=20,
        )
        self.live_version_data = {
            "containerVersionId": "1",
            "tag": [],
            "trigger": [],
            "variable": [],
        }

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_plan_generation_synthesizes_all_missing_items(self):
        builder = GtmAutoBuilder(lambda cmd, **kwargs: {})
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)

        self.assertEqual(plan.brand_id, "testbrand")
        self.assertIsNone(plan.error)
        self.assertTrue(len(plan.actions) >= 7)

        action_names = [a.name for a in plan.actions]
        self.assertIn("GA4 - Google Tag", action_names)
        self.assertIn("Google Ads - Conversion Linker", action_names)
        self.assertIn("CE - E-commerce Events", action_names)
        self.assertIn("GA4 - E-commerce Events Forwarder", action_names)
        self.assertIn("CE - generate_lead", action_names)
        self.assertIn("GA4 - generate_lead", action_names)
        self.assertIn("Meta Pixel - Base Code", action_names)
        self.assertIn("Google Ads - Google Tag", action_names)
        self.assertIn("Blocking - Cart and Checkout Pages", action_names)

        # Assert GA4 Google Tag parameter schema invariant
        ga4_tag = next(a for a in plan.actions if a.name == "GA4 - Google Tag")
        params = ga4_tag.config.get("parameter", [])
        tag_id_param = next((p for p in params if p.get("key") == "tagId"), None)
        self.assertIsNotNone(tag_id_param)
        self.assertEqual(tag_id_param.get("value"), "G-TESTGA4ID")

        # Assert GA4 Ecommerce forwarder has {{Event}}, dataLayer source, and measurementIdOverride
        ecomm_tag = next(a for a in plan.actions if a.name == "GA4 - E-commerce Events Forwarder")
        ecomm_params = ecomm_tag.config.get("parameter", [])
        ev_name = next((p.get("value") for p in ecomm_params if p.get("key") == "eventName"), None)
        self.assertEqual(ev_name, "{{Event}}")
        src = next((p.get("value") for p in ecomm_params if p.get("key") == "getEcommerceDataFrom"), None)
        self.assertEqual(src, "dataLayer")
        meas_id = next((p.get("value") for p in ecomm_params if p.get("key") == "measurementIdOverride"), None)
        self.assertEqual(meas_id, "G-TESTGA4ID")

        # Assert GA4 generate_lead has measurementIdOverride
        lead_tag = next(a for a in plan.actions if a.name == "GA4 - generate_lead")
        lead_params = lead_tag.config.get("parameter", [])
        lead_meas_id = next((p.get("value") for p in lead_params if p.get("key") == "measurementIdOverride"), None)
        self.assertEqual(lead_meas_id, "G-TESTGA4ID")

    def test_safety_gate_rejects_uninitialized_container_without_flag(self):
        empty_data = {}
        with self.assertRaises(SafetyGateError) as ctx:
            GtmSafetyGuard.verify_initialized(empty_data, allow_legacy_init=False)
        self.assertIn("Safety Gate Refusal", str(ctx.exception))
        self.assertIn("--allow-legacy-init", str(ctx.exception))

    def test_safety_gate_allows_uninitialized_container_with_flag(self):
        empty_data = {}
        GtmSafetyGuard.verify_initialized(empty_data, allow_legacy_init=True)

    def test_safety_gate_rejects_live_version_error_even_with_flag(self):
        err_data = {"error": "403 Forbidden: Insufficient permission to view container"}
        with self.assertRaises(SafetyGateError) as ctx:
            GtmSafetyGuard.verify_initialized(err_data, allow_legacy_init=True)
        self.assertIn("live version query error", str(ctx.exception))

    def test_rollback_backup_creation_and_validation(self):
        backup_path = GtmSafetyGuard.create_rollback_backup(
            account_id="111111",
            container_id="222222",
            public_id="GTM-TEST999",
            live_version_id="1",
            live_data=self.live_version_data,
            backup_dir=self.tmp_dir,
        )
        self.assertTrue(backup_path.exists())
        self.assertGreater(backup_path.stat().st_size, 0)
        loaded = json.loads(backup_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded.get("containerVersionId"), "1")

    def test_idempotency_prevents_duplicate_tags_and_triggers(self):
        # Add existing GA4 tag and CE trigger into live_version_data
        existing_tags = [
            {
                "tagId": "50",
                "name": "GA4 - Google Tag",
                "type": "googtag",
                "parameter": [{"type": "template", "key": "tagId", "value": "G-TESTGA4ID"}],
            }
        ]
        # Notice reverse key ordering to test normalized filter comparison
        existing_triggers = [
            {
                "triggerId": "70",
                "name": "CE - E-commerce Events",
                "type": "customEvent",
                "customEventFilter": [
                    {
                        "parameter": [
                            {"value": "^(view_item_list|view_item|add_to_cart|remove_from_cart|view_cart|begin_checkout|add_payment_info|add_shipping_info|purchase)$", "type": "template", "key": "arg1"},
                            {"value": "{{_event}}", "type": "template", "key": "arg0"},
                        ],
                        "type": "matchRegex",
                    }
                ],
            }
        ]
        self.live_version_data["tag"] = existing_tags
        self.live_version_data["trigger"] = existing_triggers

        builder = GtmAutoBuilder(lambda cmd, **kwargs: {})
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)

        # "GA4 - Google Tag" and "CE - E-commerce Events" should be skipped by idempotency check
        action_names = [a.name for a in plan.actions]
        self.assertNotIn("GA4 - Google Tag", action_names)
        self.assertNotIn("CE - E-commerce Events", action_names)
        # But E-commerce forwarder tag should still be planned, referencing existing trigger 70!
        ecomm_tag = next(a for a in plan.actions if a.name == "GA4 - E-commerce Events Forwarder")
        self.assertEqual(ecomm_tag.firing_trigger_ref, "70")

    def test_dry_run_does_not_mutate(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)
        options = AutoBuildOptions(execute=False)

        res = builder.execute_plan(plan, self.config, self.live_version_data, options)
        self.assertEqual(res.status, "dry_run")
        self.assertTrue(res.receipt.get("dry_run"))
        # Zero mutating commands should have been sent to mock_runner
        self.assertEqual(len(mock_calls), 0)

    def test_empty_actions_skips_execution(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = ContainerAutoBuildPlan(
            brand_id="test",
            brand_name="Test",
            account_id="111",
            container_id="222",
            public_id="GTM-TEST",
            live_version_id="1",
            actions=[],  # Empty actions
        )
        options = AutoBuildOptions(execute=True)
        res = builder.execute_plan(plan, self.config, self.live_version_data, options)
        self.assertEqual(res.status, "skipped")
        self.assertFalse(res.receipt.get("executed"))
        self.assertEqual(len(mock_calls), 0)

    def test_mutation_failure_halts_and_aborts_version_creation(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            if "workspaces list" in cmd:
                return [{"workspaceId": "5", "name": "Default Workspace"}]
            if "workspaces create" in cmd:
                return {"workspaceId": "101", "name": "AutoFix-Test"}
            if "tags create" in cmd and "GA4 - Google Tag" in cmd:
                return {"tagId": "10"}
            if "tags create" in cmd and "Google Ads - Conversion Linker" in cmd:
                return {"tagId": "11"}
            if "built-in-variables enable" in cmd:
                return {"error": "API rate limit exceeded"}
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)
        options = AutoBuildOptions(execute=True, backup_dir=self.tmp_dir)

        with self.assertRaises(SafetyGateError) as ctx:
            builder.execute_plan(plan, self.config, self.live_version_data, options)
        self.assertIn("Failed to enable built-in variables", str(ctx.exception))

        # Assert versions create was NEVER called
        ver_calls = [c for c in mock_calls if "versions create" in c[0]]
        self.assertEqual(len(ver_calls), 0)

    def test_tag_mutation_failure_halts_and_aborts_version_creation(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            if "workspaces list" in cmd:
                return [{"workspaceId": "5", "name": "Default Workspace"}]
            if "workspaces create" in cmd:
                return {"workspaceId": "101", "name": "AutoFix-Test"}
            if "tags create" in cmd:
                return {"error": "Tag creation failed: 400 Bad Request"}
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)
        options = AutoBuildOptions(execute=True, backup_dir=self.tmp_dir)

        with self.assertRaises(SafetyGateError) as ctx:
            builder.execute_plan(plan, self.config, self.live_version_data, options)
        self.assertIn("Failed to create tag", str(ctx.exception))

        ver_calls = [c for c in mock_calls if "versions create" in c[0]]
        self.assertEqual(len(ver_calls), 0)

    def test_version_creation_failure_halts_and_does_not_publish(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            if "workspaces list" in cmd:
                return [{"workspaceId": "5", "name": "Default Workspace"}]
            if "workspaces create" in cmd:
                return {"workspaceId": "101", "name": "AutoFix-Test"}
            if "triggers create" in cmd:
                return {"triggerId": "301"}
            if "tags create" in cmd:
                return {"tagId": "401"}
            if "built-in-variables enable" in cmd:
                return [{"type": "event"}]
            if "versions create" in cmd:
                return {"error": "Container version creation failed: 500 Internal Error"}
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)
        options = AutoBuildOptions(
            execute=True,
            allow_publish=True,
            confirm="222222",
            backup_dir=self.tmp_dir,
        )

        with self.assertRaises(SafetyGateError) as ctx:
            builder.execute_plan(plan, self.config, self.live_version_data, options)
        self.assertIn("Failed to create container version", str(ctx.exception))

        # Assert publish was NEVER called
        pub_calls = [c for c in mock_calls if "versions publish" in c[0]]
        self.assertEqual(len(pub_calls), 0)

    def test_publish_failure_marks_status_error(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            if "workspaces list" in cmd:
                return [{"workspaceId": "5", "name": "Default Workspace"}]
            if "workspaces create" in cmd:
                return {"workspaceId": "101", "name": "AutoFix-Test"}
            if "triggers create" in cmd:
                return {"triggerId": "301"}
            if "tags create" in cmd:
                return {"tagId": "401"}
            if "built-in-variables enable" in cmd:
                return [{"type": "event"}]
            if "versions create" in cmd:
                return {"containerVersionId": "2"}
            if "versions publish" in cmd:
                return {"error": "Permission denied: user lacks publish rights"}
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)
        options = AutoBuildOptions(
            execute=True,
            allow_publish=True,
            confirm="222222",
            backup_dir=self.tmp_dir,
        )

        res = builder.execute_plan(plan, self.config, self.live_version_data, options)
        self.assertEqual(res.status, "error")
        self.assertIn("Permission denied", res.error)
        self.assertFalse(res.receipt.get("published"))
        self.assertIn("rollback_instructions", res.receipt)

    def test_blocking_trigger_id_passed_to_tags_create(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            if "workspaces list" in cmd:
                return [{"workspaceId": "5", "name": "Default Workspace"}]
            if "workspaces create" in cmd:
                return {"workspaceId": "101", "name": "AutoFix-Test"}
            if "triggers create" in cmd:
                return {"triggerId": "999"}
            if "tags create" in cmd:
                return {"tagId": "888"}
            if "versions create" in cmd:
                return {"containerVersionId": "2"}
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = ContainerAutoBuildPlan(
            brand_id="test",
            brand_name="Test",
            account_id="111",
            container_id="222",
            public_id="GTM-TEST",
            live_version_id="1",
            actions=[
                AutoBuildItem(
                    kind="tag",
                    name="Promo Widget",
                    type="html",
                    firing_trigger_ref="2147479553",
                    blocking_trigger_ref="999",
                    config={"parameter": [{"type": "template", "key": "html", "value": "<div></div>"}]},
                )
            ],
        )
        options = AutoBuildOptions(execute=True, backup_dir=self.tmp_dir)
        builder.execute_plan(plan, self.config, self.live_version_data, options)

        tag_call = next((c for c in mock_calls if "tags create" in c[0]), None)
        self.assertIsNotNone(tag_call)
        self.assertIn("--blocking-trigger-id 999", tag_call[0])

    def test_publish_safety_confirmation_gate(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            if "workspaces list" in cmd:
                return [{"workspaceId": "5", "name": "Default Workspace"}]
            if "workspaces create" in cmd:
                return {"workspaceId": "101", "name": "AutoFix-Test"}
            if "triggers create" in cmd:
                return {"triggerId": "301"}
            if "tags create" in cmd:
                return {"tagId": "401"}
            if "versions create" in cmd:
                return {"containerVersionId": "2"}
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)
        
        # Test confirmation mismatch: container_id is 222222, but confirm is 999999
        options = AutoBuildOptions(
            execute=True,
            allow_publish=True,
            confirm="999999",
            backup_dir=self.tmp_dir,
        )

        res = builder.execute_plan(plan, self.config, self.live_version_data, options)
        self.assertEqual(res.status, "version_created_unpublished")
        self.assertIn("confirmation mismatch", res.error)
        self.assertFalse(res.receipt.get("published"))

    def test_full_execution_flow_with_publish_and_mock(self):
        mock_calls = []

        def mock_runner(cmd, **kwargs):
            mock_calls.append((cmd, kwargs))
            if "workspaces list" in cmd:
                return [{"workspaceId": "5", "name": "Default Workspace"}]
            if "workspaces create" in cmd:
                return {"workspaceId": "101", "name": "AutoFix-Test"}
            if "triggers create" in cmd:
                return {"triggerId": "301"}
            if "tags create" in cmd:
                return {"tagId": "401"}
            if "built-in-variables enable" in cmd:
                return [{"type": "event"}]
            if "versions create" in cmd:
                return {"containerVersionId": "2"}
            if "versions publish" in cmd:
                return {"containerVersionId": "2", "published": True}
            return {}

        builder = GtmAutoBuilder(mock_runner)
        plan = builder.synthesize_plan(self.config, self.audit_result, self.live_version_data)
        
        options = AutoBuildOptions(
            execute=True,
            allow_publish=True,
            confirm="222222",
            backup_dir=self.tmp_dir,
        )

        res = builder.execute_plan(plan, self.config, self.live_version_data, options)
        self.assertEqual(res.status, "published")
        self.assertEqual(res.created_version_id, "2")
        self.assertTrue(res.receipt.get("published"))
        self.assertIsNotNone(res.backup_file)

        # Check that versions publish was called with required flags
        publish_call = next((c for c in mock_calls if "versions publish" in c[0]), None)
        self.assertIsNotNone(publish_call)
        self.assertTrue(publish_call[1].get("allow_publish"))
        self.assertEqual(publish_call[1].get("confirm"), "222222")


if __name__ == "__main__":
    unittest.main()
