#!/usr/bin/env python3
"""
test_surface_gating.py - Surface gating audit: may a tag run on this page?

Fixtures mirror the Acme Luxury DTC container v29 shapes (2026-10-29), where a
Cloudflare Google tag gateway injected the container into every proxied host and
a Claspo popup appeared on the status page and over the SiteGround bot challenge.
"""

import copy
import unittest
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from portfolio_gtm_audit import evaluate_surface_gating

CLASSIFIER = "CJS - Page Surface"
ALL_PAGES, INIT = "2147479553", "2147479573"


def _cond(kind, arg0, arg1, negate=False):
    params = [
        {"type": "template", "key": "arg0", "value": arg0},
        {"type": "template", "key": "arg1", "value": arg1},
    ]
    if negate:
        params.append({"type": "boolean", "key": "negate", "value": "true"})
    return {"type": kind, "parameter": params}


def _all_event_blocker(trigger_id, condition):
    return {
        "triggerId": trigger_id,
        "type": "customEvent",
        "customEventFilter": [_cond("matchRegex", "{{_event}}", ".*")],
        "filter": [condition],
    }


NON_CUSTOMER = _all_event_blocker("57", _cond("matchRegex", "{{CJS - Page Surface}}", "^(internal|system|editor)$"))
PROMO_OFF_STOREFRONT = _all_event_blocker("58", _cond("equals", "{{CJS - Page Surface}}", "storefront", negate=True))
STOREFRONT_HOST = {
    "triggerId": "18",
    "type": "pageview",
    "filter": [_cond("matchRegex", "{{Page Hostname}}", r"^(www\.)?example-store\.com$")],
}
CART = {"triggerId": "15", "type": "pageview", "filter": [_cond("contains", "{{Page URL}}", "cart")]}

CLASPO_HTML = (
    "<script> !function (t, e, c, n) { var s = e.createElement(c); s.async = 1, "
    "s.src = 'https://scripts.claspo.io/scripts/' + n + '.js'; }(window, document, 'script', 'X'); </script>"
)


def gated_container():
    tags = [
        {"tagId": "3", "name": "GA4", "type": "googtag", "firingTriggerId": [ALL_PAGES, INIT], "blockingTriggerId": ["57"]},
        {"tagId": "5", "name": "Clarity", "type": "cvt_MQDKZ", "firingTriggerId": [ALL_PAGES], "blockingTriggerId": ["57"]},
        {
            "tagId": "25", "name": "Claspo Library", "type": "html", "firingTriggerId": [ALL_PAGES],
            "blockingTriggerId": ["15", "58"], "parameter": [{"type": "template", "key": "html", "value": CLASPO_HTML}],
        },
        {"tagId": "35", "name": "Chatwoot", "type": "html", "firingTriggerId": ["18"], "blockingTriggerId": ["15", "57"],
         "parameter": [{"type": "template", "key": "html", "value": "<script>window.chatwootSettings={}</script>"}]},
        {"tagId": "14", "name": "Old chat", "type": "html", "paused": True, "firingTriggerId": [ALL_PAGES]},
        {"tagId": "24", "name": "Ads purchase", "type": "awct", "firingTriggerId": ["22"]},
    ]
    triggers = [NON_CUSTOMER, PROMO_OFF_STOREFRONT, STOREFRONT_HOST, CART,
                {"triggerId": "22", "type": "customEvent",
                 "customEventFilter": [_cond("equals", "{{_event}}", "purchase")]}]
    variables = [{"variableId": "56", "name": CLASSIFIER, "type": "jsm"}]
    return tags, triggers, variables


def tag(tags, name):
    return next(t for t in tags if t["name"] == name)


class TestSurfaceGating(unittest.TestCase):

    def test_gated_container_passes_and_reports_its_denominator(self):
        report = evaluate_surface_gating(*gated_container(), CLASSIFIER)
        self.assertEqual(report["ungated"], [])
        self.assertTrue(report["classifier_present"])
        # GA4, Clarity, Claspo fire site-wide; paused and event-only tags are not graded.
        self.assertEqual((report["site_wide_graded"], report["site_wide_gated"]), (3, 3))
        self.assertEqual((report["promo_graded"], report["promo_allow_listed"]), (1, 1))

    def test_site_wide_tag_without_blocker_is_flagged(self):
        tags, triggers, variables = gated_container()
        tag(tags, "GA4")["blockingTriggerId"] = []
        report = evaluate_surface_gating(tags, triggers, variables, CLASSIFIER)
        self.assertEqual([u["tag"] for u in report["ungated"]], ["GA4"])
        self.assertEqual(report["site_wide_gated"], 2)

    def test_page_view_blocker_misses_initialization(self):
        tags, triggers, variables = gated_container()
        page_view_blocker = {"triggerId": "60", "type": "pageview",
                             "filter": [_cond("matchRegex", "{{CJS - Page Surface}}", "^(internal)$")]}
        triggers.append(page_view_blocker)
        tag(tags, "GA4")["blockingTriggerId"] = ["60"]
        report = evaluate_surface_gating(tags, triggers, variables, CLASSIFIER)
        self.assertEqual(len(report["ungated"]), 1)
        self.assertIn("Initialization", report["ungated"][0]["reason"])

    def test_promo_with_deny_list_blocker_is_flagged(self):
        tags, triggers, variables = gated_container()
        tag(tags, "Claspo Library")["blockingTriggerId"] = ["15", "57"]
        report = evaluate_surface_gating(tags, triggers, variables, CLASSIFIER)
        self.assertEqual([u["tag"] for u in report["ungated"]], ["Claspo Library"])
        self.assertIn("framed, editor and system", report["ungated"][0]["reason"])
        self.assertEqual(report["ungated"][0]["domains"], ["scripts.claspo.io"])

    def test_promo_gated_only_by_host_scoped_trigger_is_flagged(self):
        tags, triggers, variables = gated_container()
        claspo = tag(tags, "Claspo Library")
        claspo["firingTriggerId"], claspo["blockingTriggerId"] = ["18"], ["15"]
        report = evaluate_surface_gating(tags, triggers, variables, CLASSIFIER)
        self.assertEqual([u["tag"] for u in report["ungated"]], ["Claspo Library"])

    def test_missing_classifier_variable_is_reported(self):
        tags, triggers, _ = gated_container()
        report = evaluate_surface_gating(tags, triggers, [], CLASSIFIER)
        self.assertFalse(report["classifier_present"])

    def test_live_v27_shape_fails(self):
        """The pre-fix container: Claspo and GA4 on All Pages, cart/checkout blockers only."""
        tags, triggers, variables = gated_container()
        before = copy.deepcopy(tags)
        for t in before:
            t["blockingTriggerId"] = [b for b in t.get("blockingTriggerId", []) if b not in ("57", "58")]
        report = evaluate_surface_gating(before, triggers, [], CLASSIFIER)
        flagged = {u["tag"] for u in report["ungated"]}
        self.assertEqual(flagged, {"GA4", "Clarity", "Claspo Library"})
        self.assertEqual(report["site_wide_gated"], 0)


if __name__ == "__main__":
    unittest.main()
