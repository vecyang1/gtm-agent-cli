#!/usr/bin/env python3
"""
gtm_autobuild.py - Automated Self-Healing and Auto-Build Engine for Google Tag Manager

Provides automated synthesis, safety gating, idempotency verification, rollback backups,
and version publishing for missing conversion events, pixels, and linkers across the site portfolio.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_BACKUP_DIR = SKILL_DIR.parent / "backups"


@dataclass
class AutoBuildItem:
    kind: str  # "built_in_variable", "variable", "trigger", "tag"
    name: str
    type: str
    config: Dict[str, Any] = field(default_factory=dict)
    firing_trigger_ref: Optional[str] = None
    blocking_trigger_ref: Optional[str] = None
    reason: str = ""


@dataclass
class ContainerAutoBuildPlan:
    brand_id: str
    brand_name: str
    account_id: str
    container_id: str
    public_id: str
    live_version_id: Optional[str]
    missing_items: List[str] = field(default_factory=list)
    actions: List[AutoBuildItem] = field(default_factory=list)
    status: str = "pending"  # "pending", "dry_run", "applied", "published", "skipped", "error"
    error: Optional[str] = None
    workspace_id: Optional[str] = None
    created_version_id: Optional[str] = None
    backup_file: Optional[str] = None
    post_audit_score: Optional[int] = None
    receipt: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AutoBuildOptions:
    execute: bool = False
    allow_publish: bool = False
    confirm: Optional[str] = None
    allow_legacy_init: bool = False
    force_workspace: bool = False
    backup_dir: Path = field(default_factory=lambda: DEFAULT_BACKUP_DIR)


class SafetyGateError(Exception):
    """Raised when a mutation violates a GTM safety gate."""
    pass


class GtmSafetyGuard:
    """Enforces safety, idempotency, and rollback readiness for GTM mutations."""

    @staticmethod
    def verify_initialized(live_version_data: Dict[str, Any], allow_legacy_init: bool) -> None:
        """Refuses to mutate uninitialized or empty containers without explicit confirmation."""
        if isinstance(live_version_data, dict) and "error" in live_version_data:
            raise SafetyGateError(
                f"Safety Gate Refusal: Cannot mutate container with live version query error: {live_version_data['error']}"
            )
        if not live_version_data or not live_version_data.get("containerVersionId"):
            if not allow_legacy_init:
                raise SafetyGateError(
                    "Safety Gate Refusal: Container has no live version or appears uninitialized. "
                    "Use --allow-legacy-init to explicitly authorize first-time container initialization."
                )

    @staticmethod
    def create_rollback_backup(
        account_id: str,
        container_id: str,
        public_id: str,
        live_version_id: str,
        live_data: Dict[str, Any],
        backup_dir: Path,
    ) -> Path:
        """Persists the live container version JSON to disk before mutation and returns backup path."""
        backup_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.date.today().isoformat()
        backup_file = backup_dir / f"{date_str}-{public_id}-v{live_version_id}-before-autofix.json"
        
        backup_content = json.dumps(live_data, indent=2)
        backup_file.write_text(backup_content, encoding="utf-8")
        
        # Verify backup on disk
        if not backup_file.exists() or backup_file.stat().st_size == 0:
            raise SafetyGateError(f"Safety Gate Refusal: Failed to write non-empty rollback backup at {backup_file}")
        
        return backup_file

    @staticmethod
    def check_idempotency(
        planned_item: AutoBuildItem,
        existing_tags: List[Dict[str, Any]],
        existing_triggers: List[Dict[str, Any]],
        existing_variables: List[Dict[str, Any]],
    ) -> Tuple[bool, Optional[str]]:
        """
        Checks whether a planned resource already exists.
        Returns: (is_duplicate: bool, existing_id: Optional[str])
        """
        p_name = planned_item.name.strip().lower()
        p_type = planned_item.type.strip()

        if planned_item.kind == "trigger":
            for tr in existing_triggers:
                t_name = tr.get("name", "").strip().lower()
                t_type = tr.get("type", "")
                if t_name == p_name and t_type == p_type:
                    return True, str(tr.get("triggerId"))
                # Custom event regex match
                if p_type == "customEvent" and t_type == "customEvent":
                    p_filters = planned_item.config.get("customEventFilter", [])
                    tr_filters = tr.get("customEventFilter", [])
                    # Normalized JSON comparison
                    if p_filters and tr_filters:
                        if json.dumps(p_filters, sort_keys=True) == json.dumps(tr_filters, sort_keys=True):
                            return True, str(tr.get("triggerId"))
                        # Compare arg1 values (event regex pattern)
                        p_arg1 = next((p.get("value") for f in p_filters for p in f.get("parameter", []) if p.get("key") == "arg1"), None)
                        tr_arg1 = next((p.get("value") for f in tr_filters for p in f.get("parameter", []) if p.get("key") == "arg1"), None)
                        if p_arg1 and tr_arg1 and p_arg1.strip() == tr_arg1.strip():
                            return True, str(tr.get("triggerId"))

        elif planned_item.kind == "tag":
            p_params = planned_item.config.get("parameter", [])
            for tg in existing_tags:
                t_name = tg.get("name", "").strip().lower()
                t_type = tg.get("type", "")
                tg_params = tg.get("parameter", [])
                if t_name == p_name:
                    return True, str(tg.get("tagId"))
                # Check googtag with identical measurement ID
                if p_type == "googtag" and t_type == "googtag":
                    p_tag_id = next((p.get("value") for p in p_params if p.get("key") == "tagId"), None)
                    tg_tag_id = next((p.get("value") for p in tg_params if p.get("key") == "tagId"), None)
                    if p_tag_id and tg_tag_id and p_tag_id.strip() == tg_tag_id.strip():
                        return True, str(tg.get("tagId"))
                # Check conversion linker
                if p_type == "gclidw" and t_type == "gclidw":
                    return True, str(tg.get("tagId"))
                # Check GA4 event forwarder
                if p_type == "gaawe" and t_type == "gaawe":
                    p_ev = next((p.get("value") for p in p_params if p.get("key") == "eventName"), None)
                    tg_ev = next((p.get("value") for p in tg_params if p.get("key") == "eventName"), None)
                    if p_ev and tg_ev and p_ev == tg_ev:
                        return True, str(tg.get("tagId"))
                # Check Meta Pixel
                if p_type == "html" and t_type == "html":
                    p_html = next((p.get("value") for p in p_params if p.get("key") == "html"), "")
                    tg_html = next((p.get("value") for p in tg_params if p.get("key") == "html"), "")
                    if "fbq('init'" in p_html and "fbq('init'" in tg_html:
                        p_m = re.search(r"fbq\('init',\s*['\"](\d+)['\"]\)", p_html)
                        tg_m = re.search(r"fbq\('init',\s*['\"](\d+)['\"]\)", tg_html)
                        if p_m and tg_m and p_m.group(1) == tg_m.group(1):
                            return True, str(tg.get("tagId"))

        elif planned_item.kind == "variable":
            for vr in existing_variables:
                v_name = vr.get("name", "").strip().lower()
                if v_name == p_name:
                    return True, str(vr.get("variableId"))

        return False, None


class GtmAutoBuilder:
    """Synthesizes and executes auto-repair tracking plans."""

    def __init__(self, run_cmd_fn: Callable[..., Dict[str, Any]]):
        self.run_cmd = run_cmd_fn

    def synthesize_plan(
        self,
        config: Dict[str, Any],
        audit_result: Any,
        live_version_data: Dict[str, Any],
    ) -> ContainerAutoBuildPlan:
        plan = ContainerAutoBuildPlan(
            brand_id=config["id"],
            brand_name=config["name"],
            account_id=config["account_id"],
            container_id=config["container_id"],
            public_id=config["public_id"],
            live_version_id=str(live_version_data.get("containerVersionId", "")) or None,
        )

        existing_tags = live_version_data.get("tag", [])
        existing_triggers = live_version_data.get("trigger", [])
        existing_variables = live_version_data.get("variable", [])

        # 1. Missing GA4 Config
        if not getattr(audit_result, "ga4_configured", False):
            plan.missing_items.append("GA4 Configuration Tag")
            expected_ga4 = config.get("expected_ga4_id")
            if not expected_ga4:
                plan.error = f"Cannot auto-build GA4 tag: expected_ga4_id is not configured for {config['name']}."
            else:
                item = AutoBuildItem(
                    kind="tag",
                    name="GA4 - Google Tag",
                    type="googtag",
                    firing_trigger_ref="2147479553",  # All Pages
                    config={
                        "parameter": [
                            {"type": "template", "key": "tagId", "value": expected_ga4}
                        ]
                    },
                    reason="Deploy required GA4 measurement Google Tag on All Pages",
                )
                dup, _ = GtmSafetyGuard.check_idempotency(item, existing_tags, existing_triggers, existing_variables)
                if not dup:
                    plan.actions.append(item)

        # 2. Missing Conversion Linker
        if config.get("requires_conversion_linker") and not getattr(audit_result, "conversion_linker_present", False):
            plan.missing_items.append("Conversion Linker (gclidw)")
            item = AutoBuildItem(
                kind="tag",
                name="Google Ads - Conversion Linker",
                type="gclidw",
                firing_trigger_ref="2147479553",
                config={},
                reason="Deploy Conversion Linker for paid ads click attribution",
            )
            dup, _ = GtmSafetyGuard.check_idempotency(item, existing_tags, existing_triggers, existing_variables)
            if not dup:
                plan.actions.append(item)

        # 3. Missing E-Commerce Forwarder
        if config.get("requires_ecommerce") and not getattr(audit_result, "ecommerce_forwarding_present", False):
            plan.missing_items.append("E-Commerce Forwarding Tag & Trigger")
            # Built-in variable: event
            plan.actions.append(
                AutoBuildItem(
                    kind="built_in_variable",
                    name="event",
                    type="built_in_variable",
                    config={"types": ["event"]},
                    reason="Enable {{Event}} built-in variable for custom commerce trigger",
                )
            )
            # Custom Event Trigger
            trigger_item = AutoBuildItem(
                kind="trigger",
                name="CE - E-commerce Events",
                type="customEvent",
                config={
                    "customEventFilter": [
                        {
                            "type": "matchRegex",
                            "parameter": [
                                {"type": "template", "key": "arg0", "value": "{{_event}}"},
                                {
                                    "type": "template",
                                    "key": "arg1",
                                    "value": "^(view_item_list|view_item|add_to_cart|remove_from_cart|view_cart|begin_checkout|add_payment_info|add_shipping_info|purchase)$",
                                },
                            ],
                        }
                    ]
                },
                reason="Match all standard GA4 ecommerce dataLayer events",
            )
            dup, existing_id = GtmSafetyGuard.check_idempotency(trigger_item, existing_tags, existing_triggers, existing_variables)
            if not dup:
                plan.actions.append(trigger_item)

            # GA4 Ecommerce Event Tag
            expected_ga4 = config.get("expected_ga4_id")
            tag_params = [
                {"type": "template", "key": "eventName", "value": "{{Event}}"},
                {"type": "boolean", "key": "sendEcommerceData", "value": "true"},
                {"type": "template", "key": "getEcommerceDataFrom", "value": "dataLayer"},
            ]
            if expected_ga4:
                tag_params.append({"type": "template", "key": "measurementIdOverride", "value": expected_ga4})
            elif not plan.error:
                plan.error = f"Cannot configure GA4 Ecommerce tag: missing expected_ga4_id for {config['name']}."

            tag_item = AutoBuildItem(
                kind="tag",
                name="GA4 - E-commerce Events Forwarder",
                type="gaawe",
                firing_trigger_ref=existing_id or "CE - E-commerce Events",
                config={"parameter": tag_params},
                reason="Forward native ecommerce dataLayer object to GA4 with measurement ID override",
            )
            dup_tag, _ = GtmSafetyGuard.check_idempotency(tag_item, existing_tags, existing_triggers, existing_variables)
            if not dup_tag:
                plan.actions.append(tag_item)

        # 4. Missing Lead Gen
        if config.get("requires_lead_gen") and not getattr(audit_result, "lead_conversion_present", False):
            plan.missing_items.append("Lead Generation Conversion Tag & Trigger")
            plan.actions.append(
                AutoBuildItem(
                    kind="built_in_variable",
                    name="event",
                    type="built_in_variable",
                    config={"types": ["event"]},
                    reason="Enable {{Event}} built-in variable for lead trigger",
                )
            )
            trigger_item = AutoBuildItem(
                kind="trigger",
                name="CE - generate_lead",
                type="customEvent",
                config={
                    "customEventFilter": [
                        {
                            "type": "equals",
                            "parameter": [
                                {"type": "template", "key": "arg0", "value": "{{_event}}"},
                                {"type": "template", "key": "arg1", "value": "generate_lead"},
                            ],
                        }
                    ]
                },
                reason="Custom event trigger matching generate_lead",
            )
            dup, existing_id = GtmSafetyGuard.check_idempotency(trigger_item, existing_tags, existing_triggers, existing_variables)
            if not dup:
                plan.actions.append(trigger_item)

            expected_ga4 = config.get("expected_ga4_id")
            tag_params = [
                {"type": "template", "key": "eventName", "value": "generate_lead"},
            ]
            if expected_ga4:
                tag_params.append({"type": "template", "key": "measurementIdOverride", "value": expected_ga4})
            elif not plan.error:
                plan.error = f"Cannot configure GA4 Lead tag: missing expected_ga4_id for {config['name']}."

            tag_item = AutoBuildItem(
                kind="tag",
                name="GA4 - generate_lead",
                type="gaawe",
                firing_trigger_ref=existing_id or "CE - generate_lead",
                config={"parameter": tag_params},
                reason="Forward generate_lead event to GA4 with measurement ID override",
            )
            dup_tag, _ = GtmSafetyGuard.check_idempotency(tag_item, existing_tags, existing_triggers, existing_variables)
            if not dup_tag:
                plan.actions.append(tag_item)

        # 5. Missing Meta Pixel
        if config.get("requires_meta_pixel") and not getattr(audit_result, "meta_pixel_present", False):
            plan.missing_items.append("Meta Pixel Base Tag")
            pixel_id = config.get("expected_meta_pixel_id")
            if pixel_id:
                html_snippet = (
                    "<!-- Meta Pixel Code -->\n"
                    "<script>\n"
                    "!function(f,b,e,v,n,t,s)\n"
                    "{if(f.fbq)return;n=f.fbq=function(){n.callMethod?\n"
                    "n.callMethod.apply(n,arguments):n.queue.push(arguments)};\n"
                    "if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';\n"
                    "n.queue=[];t=b.createElement(e);t.async=!0;\n"
                    "t.src=v;s=b.getElementsByTagName(e)[0];\n"
                    "s.parentNode.insertBefore(t,s)}(window, document,'script',\n"
                    "'https://connect.facebook.net/en_US/fbevents.js');\n"
                    f"fbq('init', '{pixel_id}');\n"
                    "fbq('track', 'PageView');\n"
                    "</script>\n"
                    f"<noscript><img height=\"1\" width=\"1\" style=\"display:none\"\n"
                    f"src=\"https://www.facebook.com/tr?id={pixel_id}&ev=PageView&noscript=1\"\n"
                    "/></noscript>\n"
                    "<!-- End Meta Pixel Code -->"
                )
                tag_item = AutoBuildItem(
                    kind="tag",
                    name="Meta Pixel - Base Code",
                    type="html",
                    firing_trigger_ref="2147479553",
                    config={
                        "parameter": [
                            {"type": "template", "key": "html", "value": html_snippet},
                            {"type": "boolean", "key": "supportDocumentWrite", "value": "false"},
                        ]
                    },
                    reason="Deploy Meta Pixel base code and PageView tracking",
                )
                dup_tag, _ = GtmSafetyGuard.check_idempotency(tag_item, existing_tags, existing_triggers, existing_variables)
                if not dup_tag:
                    plan.actions.append(tag_item)
            else:
                plan.receipt.setdefault("warnings", []).append(f"Meta Pixel required for {config['name']} but expected_meta_pixel_id is missing.")

        # 6. Missing Google Ads Base Tag
        if config.get("requires_google_ads") and not getattr(audit_result, "google_ads_present", False):
            plan.missing_items.append("Google Ads Base Google Tag")
            ads_id = config.get("expected_google_ads_id")
            if ads_id:
                tag_item = AutoBuildItem(
                    kind="tag",
                    name="Google Ads - Google Tag",
                    type="googtag",
                    firing_trigger_ref="2147479553",
                    config={
                        "parameter": [
                            {"type": "template", "key": "tagId", "value": ads_id}
                        ]
                    },
                    reason="Deploy base Google Tag for Google Ads signal coverage on All Pages",
                )
                dup_tag, _ = GtmSafetyGuard.check_idempotency(tag_item, existing_tags, existing_triggers, existing_variables)
                if not dup_tag:
                    plan.actions.append(tag_item)
            else:
                plan.receipt.setdefault("warnings", []).append(f"Google Ads required for {config['name']} but expected_google_ads_id is missing.")

        # 7. Missing Blocking Triggers
        if config.get("requires_blocking_triggers") and not getattr(audit_result, "blocking_triggers_present", False):
            plan.missing_items.append("Conversion-Critical Blocking Trigger")
            plan.actions.append(
                AutoBuildItem(
                    kind="built_in_variable",
                    name="pageUrl",
                    type="built_in_variable",
                    config={"types": ["pageUrl"]},
                    reason="Enable {{Page URL}} built-in variable for blocking trigger",
                )
            )
            trigger_item = AutoBuildItem(
                kind="trigger",
                name="Blocking - Cart and Checkout Pages",
                type="pageview",
                config={
                    "autoEventFilter": [
                        {
                            "type": "matchRegex",
                            "parameter": [
                                {"type": "template", "key": "arg0", "value": "{{_url}}"},
                                {"type": "template", "key": "arg1", "value": "(cart|checkout|order-received|thank-you|receipt)"},
                            ],
                        }
                    ]
                },
                reason="Block non-essential promotional widgets on conversion paths",
            )
            dup, _ = GtmSafetyGuard.check_idempotency(trigger_item, existing_tags, existing_triggers, existing_variables)
            if not dup:
                plan.actions.append(trigger_item)

        return plan

    def execute_plan(
        self,
        plan: ContainerAutoBuildPlan,
        config: Dict[str, Any],
        live_version_data: Dict[str, Any],
        options: AutoBuildOptions,
    ) -> ContainerAutoBuildPlan:
        """Executes the auto-build plan against GTM with safety gates, workspace isolation, and verification."""
        acc_id = plan.account_id
        cont_id = plan.container_id
        pub_id = plan.public_id

        # Gate 0: Check if any actions are required
        if not plan.actions:
            plan.status = "skipped"
            plan.receipt = {
                "executed": False,
                "message": "No auto-build actions required or planned; skipping execution.",
            }
            return plan

        # Gate 1: Check Initialization
        GtmSafetyGuard.verify_initialized(live_version_data, options.allow_legacy_init)

        # Gate 2: Dry Run Check
        if not options.execute:
            plan.status = "dry_run"
            plan.receipt = {
                "dry_run": True,
                "planned_actions": [asdict(a) for a in plan.actions],
                "message": f"Dry-run plan generated with {len(plan.actions)} actions. Run with --execute to apply.",
            }
            return plan

        # Gate 3: Rollback Backup
        backup_path = GtmSafetyGuard.create_rollback_backup(
            account_id=acc_id,
            container_id=cont_id,
            public_id=pub_id,
            live_version_id=plan.live_version_id or "0",
            live_data=live_version_data,
            backup_dir=options.backup_dir,
        )
        plan.backup_file = str(backup_path)

        # Step 4: Workspace Isolation & Selection
        ws_list = self.run_cmd(f"workspaces list --account-id {acc_id} --container-id {cont_id} --output json")
        if isinstance(ws_list, dict) and "error" in ws_list:
            raise SafetyGateError(f"Failed to query workspaces: {ws_list.get('error')}")

        workspaces = ws_list if isinstance(ws_list, list) else []
        workspace_id: Optional[str] = None

        def _is_workspace_clean(status_dict: Any) -> bool:
            if not isinstance(status_dict, dict):
                return False
            if "error" in status_dict:
                return False
            for k, v in status_dict.items():
                if k in ("workspaceId", "fingerprint", "name", "tagManagerUrl", "path", "accountId", "containerId"):
                    continue
                if bool(v):
                    return False
            return True

        # Attempt to create a dedicated workspace
        ts_suffix = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        ws_name = f"AutoFix-{ts_suffix}"
        create_ws_res = self.run_cmd(
            f"workspaces create --account-id {acc_id} --container-id {cont_id} --name '{ws_name}' --output json",
            allow_mutation=True,
        )

        if isinstance(create_ws_res, dict) and create_ws_res.get("workspaceId"):
            workspace_id = str(create_ws_res["workspaceId"])
        else:
            # Fall back to an existing clean workspace (e.g. Default Workspace with 0 pending changes)
            for ws in workspaces:
                candidate_id = str(ws.get("workspaceId"))
                status_res = self.run_cmd(
                    f"workspaces status --account-id {acc_id} --container-id {cont_id} --workspace-id {candidate_id} --output json"
                )
                if _is_workspace_clean(status_res) or options.force_workspace:
                    workspace_id = candidate_id
                    break

        if not workspace_id:
            raise SafetyGateError(
                f"Could not allocate or find a clean workspace in container {pub_id}. "
                "All workspaces have pending changes. Pass --force-workspace to mutate the active workspace."
            )

        plan.workspace_id = workspace_id

        # Step 5: Execute Planned Actions
        created_triggers: Dict[str, str] = {}
        execution_log: List[Dict[str, Any]] = []

        for action in plan.actions:
            if action.kind == "built_in_variable":
                types = ",".join(action.config.get("types", []))
                res = self.run_cmd(
                    f"built-in-variables enable --types {types} --account-id {acc_id} --container-id {cont_id} --workspace-id {workspace_id} --output json",
                    allow_mutation=True,
                )
                if isinstance(res, dict) and "error" in res:
                    raise SafetyGateError(f"Failed to enable built-in variables '{action.name}': {res['error']}")
                execution_log.append({"action": action.name, "result": res})

            elif action.kind == "trigger":
                cfg_json = json.dumps(action.config)
                res = self.run_cmd(
                    f"triggers create --name '{action.name}' --type '{action.type}' --config '{cfg_json}' --account-id {acc_id} --container-id {cont_id} --workspace-id {workspace_id} --output json",
                    allow_mutation=True,
                )
                if isinstance(res, dict) and "error" in res:
                    raise SafetyGateError(f"Failed to create trigger '{action.name}': {res['error']}")
                tr_id = str(res.get("triggerId", ""))
                if not tr_id:
                    raise SafetyGateError(f"Trigger creation for '{action.name}' returned no triggerId: {res}")
                created_triggers[action.name] = tr_id
                execution_log.append({"action": action.name, "triggerId": tr_id, "result": res})

            elif action.kind == "tag":
                # Resolve firing trigger ID
                firing_id = action.firing_trigger_ref or "2147479553"
                if firing_id in created_triggers:
                    firing_id = created_triggers[firing_id]

                # Resolve blocking trigger ID
                blocking_arg = ""
                if action.blocking_trigger_ref:
                    blk_id = action.blocking_trigger_ref
                    if blk_id in created_triggers:
                        blk_id = created_triggers[blk_id]
                    blocking_arg = f" --blocking-trigger-id {blk_id}"

                cfg_json = json.dumps(action.config)
                res = self.run_cmd(
                    f"tags create --name '{action.name}' --type '{action.type}' --config '{cfg_json}' --firing-trigger-id {firing_id}{blocking_arg} --account-id {acc_id} --container-id {cont_id} --workspace-id {workspace_id} --output json",
                    allow_mutation=True,
                )
                if isinstance(res, dict) and "error" in res:
                    raise SafetyGateError(f"Failed to create tag '{action.name}': {res['error']}")
                tg_id = str(res.get("tagId", ""))
                if not tg_id:
                    raise SafetyGateError(f"Tag creation for '{action.name}' returned no tagId: {res}")
                execution_log.append({"action": action.name, "tagId": tg_id, "result": res})

        # Step 6: Create Version
        date_iso = datetime.date.today().isoformat()
        ver_name = f"AutoFix Tracking {date_iso}"
        ver_notes = f"Auto-built tracking resources: {', '.join(a.name for a in plan.actions)}"
        ver_res = self.run_cmd(
            f"versions create --name '{ver_name}' --notes '{ver_notes}' --account-id {acc_id} --container-id {cont_id} --workspace-id {workspace_id} --output json",
            allow_mutation=True,
        )
        if isinstance(ver_res, dict) and "error" in ver_res:
            raise SafetyGateError(f"Failed to create container version: {ver_res['error']}")

        new_ver_id = str(ver_res.get("containerVersionId", ""))
        if not new_ver_id and isinstance(ver_res, dict) and "containerVersion" in ver_res:
            new_ver_id = str(ver_res["containerVersion"].get("containerVersionId", ""))

        if not new_ver_id:
            raise SafetyGateError(f"Version creation returned no containerVersionId: {ver_res}")

        plan.created_version_id = new_ver_id

        # Step 7: Publish Version (if requested & confirmed)
        if options.allow_publish:
            if options.confirm != cont_id and options.confirm != "all":
                plan.status = "version_created_unpublished"
                plan.error = f"Publish confirmation mismatch: expected --confirm {cont_id} or --confirm all, got '{options.confirm}'"
                plan.receipt = {
                    "executed": True,
                    "published": False,
                    "version_id": new_ver_id,
                    "workspace_id": workspace_id,
                    "log": execution_log,
                    "rollback_instructions": f"gtm-agent raw --allow-mutation --allow-publish --confirm {cont_id} -- versions publish --account-id {acc_id} --container-id {cont_id} --version-id {plan.live_version_id} --output json",
                }
                return plan

            pub_res = self.run_cmd(
                f"versions publish --account-id {acc_id} --container-id {cont_id} --version-id {new_ver_id} --output json",
                allow_mutation=True,
                allow_publish=True,
                confirm=cont_id,
            )
            if isinstance(pub_res, dict) and "error" in pub_res:
                plan.status = "error"
                plan.error = f"Failed to publish version {new_ver_id}: {pub_res['error']}"
                plan.receipt = {
                    "executed": True,
                    "published": False,
                    "version_id": new_ver_id,
                    "workspace_id": workspace_id,
                    "error": pub_res["error"],
                    "log": execution_log,
                    "rollback_instructions": f"gtm-agent raw --allow-mutation --allow-publish --confirm {cont_id} -- versions publish --account-id {acc_id} --container-id {cont_id} --version-id {plan.live_version_id} --output json",
                }
                return plan

            plan.status = "published"
            plan.receipt = {
                "executed": True,
                "published": True,
                "version_id": new_ver_id,
                "workspace_id": workspace_id,
                "publish_result": pub_res,
                "log": execution_log,
                "rollback_instructions": f"gtm-agent raw --allow-mutation --allow-publish --confirm {cont_id} -- versions publish --account-id {acc_id} --container-id {cont_id} --version-id {plan.live_version_id} --output json",
            }
        else:
            plan.status = "version_created_unpublished"
            plan.receipt = {
                "executed": True,
                "published": False,
                "version_id": new_ver_id,
                "workspace_id": workspace_id,
                "log": execution_log,
                "note": f"Version {new_ver_id} created but not published. Re-run with --allow-publish --confirm {cont_id} to publish live.",
            }

        return plan
