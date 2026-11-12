#!/usr/bin/env python3
"""Unit and integration tests for gtm_history.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import gtm_history  # noqa: E402


def _make_version(
    vid: int,
    name: str = "Version",
    fingerprint: str = "1700000000000",
    tags=None,
    triggers=None,
    variables=None,
    folders=None,
    templates=None,
    description: str = "",
):
    return {
        "accountId": "123",
        "containerId": "456",
        "containerVersionId": str(vid),
        "name": name,
        "description": description,
        "fingerprint": fingerprint,
        "path": f"accounts/123/containers/456/versions/{vid}",
        "tagManagerUrl": f"https://tagmanager.google.com/#/v{vid}",
        "container": {
            "accountId": "123",
            "containerId": "456",
            "name": "Example Test Container",
            "publicId": "GTM-EXAMPLE1",
        },
        "folder": folders if folders is not None else [{"folderId": "73", "name": "AdVendor", "fingerprint": str(100 + vid)}],
        "trigger": triggers if triggers is not None else [{"triggerId": "5", "name": "e-purchase", "type": "customEvent", "fingerprint": str(200 + vid)}],
        "variable": variables if variables is not None else [
            {
                "variableId": "49",
                "name": "GA4_Measurement_id",
                "type": "c",
                "parameter": [{"type": "template", "key": "value", "value": "G-OLD111"}],
            },
            {
                "variableId": "88",
                "name": "CJS - Helper",
                "type": "jsm",
                "parameter": [{"type": "template", "key": "javascript", "value": "function() { return 1; }"}],
            },
        ],
        "customTemplate": templates if templates is not None else [
            {
                "templateId": "16",
                "name": "Custom Pixel",
                "templateData": "___INFO___\n{}\n___SANDBOXED_JS_FOR_WEB_TEMPLATE___\nlog('v1');",
                "fingerprint": str(300 + vid),
            }
        ],
        "tag": tags if tags is not None else [
            {
                "tagId": "6",
                "name": "GA4 config",
                "type": "googtag",
                "firingTriggerId": ["2147479553"],
                "parameter": [{"type": "template", "key": "tagId", "value": "{{GA4_Measurement_id}}"}],
                "fingerprint": str(400 + vid),
                "path": f"accounts/123/containers/456/versions/{vid}/tags/6",
            },
            {
                "tagId": "89",
                "name": "AdVendor - Basket Tag",
                "type": "html",
                "paused": False,
                "parentFolderId": "73",
                "firingTriggerId": ["5"],
                "parameter": [
                    {
                        "type": "template",
                        "key": "html",
                        "value": '<script src="https://example-vendor.invalid/js/ld.js"></script>\n<script>console.log("v1");</script>',
                    }
                ],
                "fingerprint": str(500 + vid),
            },
        ],
        "builtInVariable": [{"type": "pageUrl", "name": "Page URL"}],
    }


class GtmHistoryTests(unittest.TestCase):
    def test_diff_ignores_volatile_metadata_and_detects_semantic_and_code_changes(self):
        v1 = _make_version(1, "Baseline", fingerprint="1685374885021")
        v2_tags = [
            _make_version(2)["tag"][0],
            {
                "tagId": "89",
                "name": "AdVendor - Basket Tag",
                "type": "html",
                "paused": True,
                "parentFolderId": "73",
                "firingTriggerId": ["2147479573"],
                "parameter": [
                    {
                        "type": "template",
                        "key": "html",
                        "value": '<script src="https://example-vendor.invalid/js/ld.js"></script>\n<script>console.log("v2");</script>',
                    }
                ],
                "fingerprint": "9999999999",
            },
            {
                "tagId": "138",
                "name": "AW - Conversion Tag B",
                "type": "awud",
                "firingTriggerId": ["5"],
                "parameter": [{"type": "template", "key": "conversionId", "value": "999999999"}],
            },
        ]
        # Wrap v2 like GTM UI export format
        v2_wrapped = {"exportFormatVersion": 2, "containerVersion": _make_version(2, "Pause AdVendor and add AW", fingerprint="1792421946863", tags=v2_tags)}

        d = gtm_history.diff_versions(v1, v2_wrapped)
        self.assertEqual(d["summary"]["addedCount"], 1)
        self.assertEqual(d["summary"]["removedCount"], 0)
        self.assertEqual(d["summary"]["changedCount"], 1)
        self.assertEqual(d["added"][0]["id"], "138")
        self.assertEqual(d["added"][0]["firingTriggers"], ["5 (e-purchase)"])

        ch = d["changed"][0]
        self.assertEqual(ch["id"], "89")
        fields = {f["field"]: f for f in ch["fieldChanges"]}
        self.assertIn("paused", fields)
        self.assertEqual((fields["paused"]["before"], fields["paused"]["after"]), (False, True))
        self.assertIn("firingTriggerId", fields)
        self.assertEqual(fields["firingTriggerId"]["after"], ["2147479573 (Initialization - All Pages)"])
        self.assertIn("parameter.html", fields)
        self.assertTrue(any('+ <script>console.log("v2");</script>'.replace("+ <", "+<") in line or '+<script>console.log("v2");</script>' in line for line in ch["codeDiff"]))

    def test_public_repo_safety_guard_and_nested_git_guard(self):
        repo_root = Path(__file__).resolve().parents[3]
        unsafe_target = repo_root / "client_roter_secret_dump"
        with self.assertRaises(PermissionError):
            gtm_history.assert_safe_output_dir(unsafe_target)

        # Gitignored backups/ directory inside public repo is allowed
        ignored_target = repo_root / "backups" / "tmp_test_backup"
        gtm_history.assert_safe_output_dir(ignored_target)

        # Nested .git inside any existing git repository must always be refused
        with tempfile.TemporaryDirectory() as tmp:
            parent_repo = Path(tmp) / "parent_repo"
            parent_repo.mkdir()
            subprocess.run(["git", "init", str(parent_repo)], capture_output=True, check=True)
            nested = parent_repo / "sub" / "gtm_git"
            with self.assertRaises(PermissionError):
                gtm_history.assert_safe_git_repo(nested)

    def test_build_bundle_escapes_script_tags_and_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vdir = root / "versions"
            vdir.mkdir()
            v1 = _make_version(1, "Init", fingerprint="1685374885021")
            v2 = _make_version(
                2,
                "Update HTML",
                fingerprint="1792421946863",
                tags=[
                    _make_version(2)["tag"][0],
                    {
                        "tagId": "89",
                        "name": "AdVendor - Basket Tag",
                        "type": "html",
                        "paused": True,
                        "parentFolderId": "73",
                        "firingTriggerId": ["5"],
                        "parameter": [{"type": "template", "key": "html", "value": "<script>alert('</script>');</script>"}],
                    },
                ],
            )
            (vdir / "gtm_v01.json").write_text(json.dumps(v1), encoding="utf-8")
            (vdir / "gtm_v02.json").write_text(json.dumps(v2), encoding="utf-8")

            res = gtm_history.build_archive_artifacts(vdir)
            self.assertTrue((vdir / "CHANGELOG.md").exists())
            self.assertTrue((vdir / "diff_series.json").exists())
            self.assertTrue((vdir / "history_viewer.html").exists())
            self.assertTrue((vdir / "latest" / "manifest.json").exists())
            self.assertTrue((vdir / "latest" / "tags" / "89__AdVendor_-_Basket_Tag.html").exists())
            self.assertTrue((vdir / "latest" / "variables" / "88__CJS_-_Helper.js").exists())
            self.assertTrue((vdir / "latest" / "templates" / "16__Custom_Pixel.tpl").exists())

            html_text = (vdir / "history_viewer.html").read_text(encoding="utf-8")
            # Embedded JSON must escape </script> inside Custom HTML so the JSON tag never closes prematurely
            script_start = html_text.index('<script id="gtm-history-data" type="application/json">')
            script_end = html_text.index("</script>\n  <script>", script_start)
            embedded_slice = html_text[script_start + len('<script id="gtm-history-data" type="application/json">'):script_end]
            self.assertNotIn("</script>", embedded_slice)
            parsed_embedded = json.loads(embedded_slice.replace("<\\/", "</"))
            self.assertEqual(parsed_embedded["container"]["totalVersions"], 2)

            changelog = (vdir / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("v02 — Update HTML", changelog)
            self.assertIn("`paused`: `false` -> `true`", changelog)
            self.assertEqual(res["container"]["latestVersion"], 2)

    def test_git_replay_creates_chronological_commits_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_dir = root / "private_history_git"
            versions = [
                _make_version(1, "Init", fingerprint="1685374885021"),
                _make_version(
                    2,
                    "Add AW",
                    fingerprint="1792421946863",
                    tags=_make_version(2)["tag"] + [{"tagId": "138", "name": "AW", "type": "awud"}],
                ),
            ]
            first = gtm_history.replay_versions_to_git(versions, git_dir)
            self.assertEqual(first["committed"], 2)
            self.assertEqual(first["skippedExisting"], 0)
            self.assertEqual(first["latestTag"], "v02")

            log_out = subprocess.run(["git", "-C", str(git_dir), "log", "--oneline"], capture_output=True, text=True, check=True).stdout
            self.assertIn("v02: Add AW", log_out)
            self.assertIn("v01: Init", log_out)

            # Re-running skips already tagged commits
            second = gtm_history.replay_versions_to_git(versions, git_dir)
            self.assertEqual(second["committed"], 0)
            self.assertEqual(second["skippedExisting"], 2)

    def test_archive_remote_container_caches_existing_and_validates_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "archive"
            out.mkdir()
            (out / "gtm_v01.json").write_text(json.dumps(_make_version(1, "Cached v1")), encoding="utf-8")

            calls = []

            def fake_cli(cmd: str):
                calls.append(cmd)
                if cmd.startswith("version-headers list"):
                    return [{"containerVersionId": "1"}, {"containerVersionId": "2"}]
                if "--version-id 2" in cmd:
                    return _make_version(2, "Fetched v2")
                raise AssertionError(f"Unexpected call: {cmd}")

            res = gtm_history.archive_remote_container("123", "456", out, cli_runner=fake_cli)
            self.assertEqual(res["cached"], 1)
            self.assertEqual(res["downloaded"], 1)
            self.assertEqual(len(calls), 2)
            self.assertTrue((out / "gtm_v02.json").exists())

            with self.assertRaises(ValueError):
                gtm_history.archive_remote_container("606;rm -rf /", "456", out, cli_runner=fake_cli)

    def test_search_and_lifecycle_trace(self):
        v1 = _make_version(1, "Init")
        v2 = _make_version(
            2,
            "Remove AdVendor add AW",
            tags=[
                v1["tag"][0],
                {"tagId": "138", "name": "AW - Conversion Tag B", "type": "awud"},
            ],
        )
        matches = gtm_history.search_archive([v1, v2], "AW - Conversion", version_scope="latest")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], "138")

        events = gtm_history.trace_entity_lifecycle([v1, v2], "AdVendor - Basket")
        event_types = [e["event"] for e in events]
        self.assertIn("present_in_baseline", event_types)
        self.assertIn("removed", event_types)


if __name__ == "__main__":
    unittest.main()
