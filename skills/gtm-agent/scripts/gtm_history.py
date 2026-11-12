#!/usr/bin/env python3
"""
gtm_history.py - Read-only archival, unpacking, semantic diffing, private Git
timeline replay, and interactive Change Explorer UI for GTM Container Versions.

Canonical owner inside gtm-agent for historical container inspection.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

try:
    from portfolio_gtm_audit import (
        APPROVED_VENDOR_DOMAINS,
        HIJACKED_OR_DEPRECATED_DOMAINS,
        extract_domains_from_html,
        run_gtm_cli,
    )
except ImportError:
    sys.path.insert(0, str(SCRIPT_DIR))
    from portfolio_gtm_audit import (  # type: ignore
        APPROVED_VENDOR_DOMAINS,
        HIJACKED_OR_DEPRECATED_DOMAINS,
        extract_domains_from_html,
        run_gtm_cli,
    )


VIEWER_TEMPLATE_PATH = SCRIPT_DIR / "gtm_history_viewer.html"
DEFAULT_ARCHIVE_ROOT = Path.home() / ".local" / "share" / "gtm-agent" / "archives"
DEFAULT_GIT_HISTORY_ROOT = Path.home() / ".local" / "share" / "gtm-agent" / "private-git-history"

NOISE_KEYS = frozenset({"fingerprint", "path", "tagManagerUrl", "workspaceId"})
BUILTIN_TRIGGER_NAMES: Dict[str, str] = {
    "2147479553": "All Pages",
    "2147479572": "Consent Initialization - All Pages",
    "2147479573": "Initialization - All Pages",
}

RESOURCE_SPECS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("tag", "tags", ("tagId", "name", "path")),
    ("trigger", "triggers", ("triggerId", "name", "path")),
    ("variable", "variables", ("variableId", "name", "path")),
    ("folder", "folders", ("folderId", "name", "path")),
    ("customTemplate", "customTemplates", ("templateId", "name", "path")),
    ("builtInVariable", "builtInVariables", ("type", "name", "path")),
    ("client", "clients", ("clientId", "name", "path")),
    ("transformation", "transformations", ("transformationId", "name", "path")),
    ("zone", "zones", ("zoneId", "name", "path")),
    ("gtagConfig", "gtagConfigs", ("gtagConfigId", "name", "path")),
]

API_KEY_TO_KIND = {api_k: kind for api_k, kind, _ in RESOURCE_SPECS}
KIND_TO_ID_FIELDS = {kind: id_fields for _, kind, id_fields in RESOURCE_SPECS}
PUBLIC_REPO_HINTS = ("gtm-agent-cli",)


def _ensure_local_bin_in_path() -> None:
    local_bin = str(Path.home() / ".local" / "bin")
    go_bin = str(Path.home() / "go" / "bin")
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for extra in (local_bin, go_bin):
        if extra not in parts:
            parts.insert(0, extra)
    os.environ["PATH"] = os.pathsep.join(parts)


def validate_numeric_id(value: str, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned.isdigit() or int(cleaned) <= 0:
        raise ValueError(f"{label} must be a positive integer string, got {value!r}")
    return cleaned


def _nearest_existing_dir(path: Path) -> Path:
    cur = path.resolve()
    while not cur.exists() and cur.parent != cur:
        cur = cur.parent
    return cur


def _git_output(cwd: Path, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return None


def assert_safe_output_dir(target_dir: Path, allow_unsafe_out: bool = False) -> None:
    """Prevent accidental client GTM backup commits into public tool repositories."""
    resolved = target_dir.expanduser().resolve()
    probe_dir = _nearest_existing_dir(resolved)
    repo_root_str = _git_output(probe_dir, "rev-parse", "--show-toplevel")
    if not repo_root_str:
        return
    repo_root = Path(repo_root_str).resolve()
    remote_url = (_git_output(repo_root, "config", "--get", "remote.origin.url") or "").lower()
    is_public_tool_repo = any(hint in remote_url for hint in PUBLIC_REPO_HINTS) or repo_root.name == "26.05.24-gtm-agent-cli"
    if not is_public_tool_repo:
        return
    # Check whether target is explicitly gitignored (for example snapshots/ or backups/)
    probe_target = resolved
    if resolved.exists():
        ignored = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", str(probe_target)],
            capture_output=True,
            timeout=5,
        ).returncode == 0
    else:
        # Check relative prefix or synthetic dummy child inside repo
        try:
            rel = resolved.relative_to(repo_root)
            rel_parts = rel.parts
            ignored = bool(rel_parts and rel_parts[0] in {"backups", "snapshots", "reports", "tmp"})
        except ValueError:
            ignored = False
    if ignored or allow_unsafe_out:
        return
    raise PermissionError(
        f"Refusing to write GTM history archive into tracked public repo {repo_root} ({resolved}). "
        f"Use a private vault path or external archive directory such as {DEFAULT_ARCHIVE_ROOT}, "
        "or pass --allow-unsafe-out inside an ignored path."
    )


def assert_safe_git_repo(git_repo_dir: Path) -> None:
    """Refuse creating a nested .git inside an existing git working tree."""
    resolved = git_repo_dir.expanduser().resolve()
    for ancestor in resolved.parents:
        if (ancestor / ".git").exists():
            raise PermissionError(
                f"Refusing to create a nested git repository inside {ancestor}. "
                f"Store git-replay history outside existing repos, e.g. under {DEFAULT_GIT_HISTORY_ROOT}."
            )


def safe_slug(text: str, max_len: int = 64) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip()).strip("._-")
    if not slug:
        slug = "unnamed"
    return slug[:max_len]


def fingerprint_to_utc(fp: Any) -> str:
    raw = str(fp or "").strip()
    if not raw.isdigit():
        return ""
    val = int(raw)
    if val <= 0:
        return ""
    seconds = val / 1000.0 if val > 10_000_000_000 else float(val)
    try:
        dt = datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OverflowError, OSError, ValueError):
        return ""


def fingerprint_to_iso(fp: Any) -> str:
    raw = str(fp or "").strip()
    if not raw.isdigit():
        return ""
    val = int(raw)
    if val <= 0:
        return ""
    seconds = val / 1000.0 if val > 10_000_000_000 else float(val)
    try:
        dt = datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return ""


def unwrap_container_version(data: Dict[str, Any]) -> Dict[str, Any]:
    """Accepts both flat API ContainerVersion payloads and GTM UI export wrappers."""
    if not isinstance(data, dict):
        raise ValueError("Container version payload must be a JSON object")
    if isinstance(data.get("containerVersion"), dict):
        return data["containerVersion"]
    return data


def is_container_version_payload(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    inner = unwrap_container_version(data)
    if "containerVersionId" in inner:
        return True
    if isinstance(inner.get("container"), dict) and any(k in inner for k, _, _ in RESOURCE_SPECS):
        return True
    return False


def get_resource_id(kind: str, item: Dict[str, Any]) -> str:
    for field in KIND_TO_ID_FIELDS.get(kind, ("name", "path")):
        val = item.get(field)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return ""


def get_parameter_value(item: Dict[str, Any], target_key: str) -> Optional[str]:
    for param in item.get("parameter", []) or []:
        if isinstance(param, dict) and param.get("key") == target_key:
            val = param.get("value")
            return None if val is None else str(val)
    return None


def _simplify_gtm_value(val: Any) -> Any:
    if isinstance(val, list):
        out: List[Any] = []
        for elem in val:
            if isinstance(elem, dict) and elem.get("type") == "map" and isinstance(elem.get("map"), list):
                row = {}
                for kv in elem["map"]:
                    if isinstance(kv, dict) and kv.get("key") is not None:
                        row[str(kv["key"])] = _simplify_gtm_value(kv.get("value", kv.get("list", kv.get("map"))))
                out.append(row)
            elif isinstance(elem, dict):
                out.append(_simplify_gtm_value(elem))
            else:
                out.append(elem)
        return out
    if isinstance(val, dict):
        return {k: _simplify_gtm_value(v) for k, v in sorted(val.items())}
    return val


def extract_parameter_map(item: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for param in item.get("parameter", []) or []:
        if not isinstance(param, dict):
            continue
        key = str(param.get("key") or "")
        if not key:
            continue
        if "value" in param:
            result[key] = param.get("value")
        elif "list" in param:
            result[key] = _simplify_gtm_value(param.get("list"))
        elif "map" in param:
            result[key] = _simplify_gtm_value(param.get("map"))
        else:
            result[key] = param
    return result


def extract_code_payload(kind: str, item: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Return (source_text, file_extension) when a resource contains inline code."""
    if kind == "tags":
        html_code = get_parameter_value(item, "html")
        if html_code is not None:
            return html_code, ".html"
    elif kind == "variables":
        js_code = get_parameter_value(item, "javascript")
        if js_code is not None:
            return js_code, ".js"
    elif kind == "customTemplates":
        tpl = item.get("templateData")
        if isinstance(tpl, str):
            return tpl, ".tpl"
    return None


def strip_noise(item: Dict[str, Any], include_metadata: bool = False) -> Dict[str, Any]:
    if include_metadata:
        return dict(item)
    return {k: v for k, v in item.items() if k not in NOISE_KEYS}


def resolve_trigger_names(trigger_ids: Any, triggers_by_id: Dict[str, str]) -> List[str]:
    if not trigger_ids:
        return []
    if isinstance(trigger_ids, (str, int)):
        ids = [str(trigger_ids)]
    elif isinstance(trigger_ids, list):
        ids = [str(x) for x in trigger_ids]
    else:
        return []
    resolved: List[str] = []
    for tid in ids:
        name = triggers_by_id.get(tid) or BUILTIN_TRIGGER_NAMES.get(tid)
        resolved.append(f"{tid} ({name})" if name else tid)
    return resolved


def classify_domain(domain: str) -> str:
    d = domain.lower().strip()
    if any(d == bad or d.endswith("." + bad) for bad in HIJACKED_OR_DEPRECATED_DOMAINS):
        return "hijacked_or_deprecated"
    if any(d == ok or d.endswith("." + ok) for ok in APPROVED_VENDOR_DOMAINS):
        return "approved"
    return "unlisted"


def extract_entity_summary(kind: str, item: Dict[str, Any], triggers_by_id: Dict[str, str], folders_by_id: Dict[str, str]) -> Dict[str, Any]:
    eid = get_resource_id(kind, item)
    name = str(item.get("name") or eid)
    folder_id = str(item.get("parentFolderId") or "")
    folder_name = folders_by_id.get(folder_id, "") if folder_id else ""
    code_info = extract_code_payload(kind, item)
    domains: List[str] = []
    if code_info and code_info[1] in (".html", ".js"):
        domains = extract_domains_from_html(code_info[0])

    return {
        "kind": kind,
        "id": eid,
        "name": name,
        "type": str(item.get("type") or item.get("tagType") or item.get("triggerType") or item.get("variableType") or ""),
        "paused": bool(item.get("paused", False)),
        "folderId": folder_id,
        "folderName": folder_name,
        "firingTriggers": resolve_trigger_names(item.get("firingTriggerId"), triggers_by_id),
        "blockingTriggers": resolve_trigger_names(item.get("blockingTriggerId"), triggers_by_id),
        "codeExtension": code_info[1] if code_info else "",
        "codeLength": len(code_info[0]) if code_info else 0,
        "domains": domains,
    }


def compute_field_changes(
    kind: str,
    before_item: Dict[str, Any],
    after_item: Dict[str, Any],
    before_triggers: Dict[str, str],
    after_triggers: Dict[str, str],
    before_folders: Dict[str, str],
    after_folders: Dict[str, str],
    include_metadata: bool = False,
) -> Tuple[List[Dict[str, Any]], Optional[List[str]]]:
    """Compute granular field-level differences and optional unified code diff."""
    b_clean = strip_noise(before_item, include_metadata=include_metadata)
    a_clean = strip_noise(after_item, include_metadata=include_metadata)
    all_keys = sorted(set(b_clean.keys()) | set(a_clean.keys()))
    changes: List[Dict[str, Any]] = []
    code_diff: Optional[List[str]] = None

    for key in all_keys:
        b_val = b_clean.get(key)
        a_val = a_clean.get(key)
        if b_val == a_val:
            continue

        if key == "parameter":
            b_params = extract_parameter_map(b_clean)
            a_params = extract_parameter_map(a_clean)
            for pkey in sorted(set(b_params.keys()) | set(a_params.keys())):
                bp = b_params.get(pkey)
                ap = a_params.get(pkey)
                if bp == ap:
                    continue
                if pkey in ("html", "javascript") and (isinstance(bp, str) or isinstance(ap, str)):
                    code_diff = list(
                        difflib.unified_diff(
                            (bp or "").splitlines(),
                            (ap or "").splitlines(),
                            fromfile=f"before/{pkey}",
                            tofile=f"after/{pkey}",
                            lineterm="",
                            n=3,
                        )
                    )
                    changes.append({
                        "field": f"parameter.{pkey}",
                        "before": f"({len(bp or '')} chars)" if bp is not None else None,
                        "after": f"({len(ap or '')} chars)" if ap is not None else None,
                        "isCode": True,
                    })
                else:
                    changes.append({
                        "field": f"parameter.{pkey}",
                        "before": bp,
                        "after": ap,
                    })
            continue

        if key == "templateData":
            code_diff = list(
                difflib.unified_diff(
                    str(b_val or "").splitlines(),
                    str(a_val or "").splitlines(),
                    fromfile="before/template.tpl",
                    tofile="after/template.tpl",
                    lineterm="",
                    n=3,
                )
            )
            changes.append({
                "field": "templateData",
                "before": f"({len(str(b_val or ''))} chars)" if b_val is not None else None,
                "after": f"({len(str(a_val or ''))} chars)" if a_val is not None else None,
                "isCode": True,
            })
            continue

        if key in ("firingTriggerId", "blockingTriggerId"):
            changes.append({
                "field": key,
                "before": resolve_trigger_names(b_val, before_triggers),
                "after": resolve_trigger_names(a_val, after_triggers),
            })
            continue

        if key == "parentFolderId":
            b_desc = f"{b_val} ({before_folders.get(str(b_val), '')})" if b_val and str(b_val) in before_folders else b_val
            a_desc = f"{a_val} ({after_folders.get(str(a_val), '')})" if a_val and str(a_val) in after_folders else a_val
            changes.append({"field": "parentFolderId", "before": b_desc, "after": a_desc})
            continue

        changes.append({"field": key, "before": b_val, "after": a_val})

    return changes, code_diff


def _build_lookup_maps(ver: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    triggers = {
        str(t.get("triggerId")): str(t.get("name") or t.get("triggerId"))
        for t in ver.get("trigger", []) or []
        if isinstance(t, dict) and t.get("triggerId") is not None
    }
    folders = {
        str(f.get("folderId")): str(f.get("name") or f.get("folderId"))
        for f in ver.get("folder", []) or []
        if isinstance(f, dict) and f.get("folderId") is not None
    }
    return triggers, folders


def diff_versions(
    before_raw: Dict[str, Any],
    after_raw: Dict[str, Any],
    include_metadata: bool = False,
) -> Dict[str, Any]:
    """Produce structured semantic + code diff between two ContainerVersions."""
    before = unwrap_container_version(before_raw)
    after = unwrap_container_version(after_raw)
    b_triggers, b_folders = _build_lookup_maps(before)
    a_triggers, a_folders = _build_lookup_maps(after)

    added: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    changed: List[Dict[str, Any]] = []

    for api_key, kind, _ in RESOURCE_SPECS:
        b_map = {}
        for item in before.get(api_key, []) or []:
            if isinstance(item, dict):
                b_map[get_resource_id(kind, item)] = item
        a_map = {}
        for item in after.get(api_key, []) or []:
            if isinstance(item, dict):
                a_map[get_resource_id(kind, item)] = item

        for eid in sorted(a_map.keys()):
            if eid not in b_map:
                a_item = a_map[eid]
                summary = extract_entity_summary(kind, a_item, a_triggers, a_folders)
                code_info = extract_code_payload(kind, a_item)
                added.append({
                    **summary,
                    "parameters": extract_parameter_map(a_item),
                    "code": code_info[0] if code_info else None,
                    "item": strip_noise(a_item, include_metadata=include_metadata),
                })
                continue

            b_item = b_map[eid]
            a_item = a_map[eid]
            if strip_noise(b_item, include_metadata=include_metadata) != strip_noise(a_item, include_metadata=include_metadata):
                field_changes, code_diff = compute_field_changes(
                    kind,
                    b_item,
                    a_item,
                    b_triggers,
                    a_triggers,
                    b_folders,
                    a_folders,
                    include_metadata=include_metadata,
                )
                if field_changes:
                    b_sum = extract_entity_summary(kind, b_item, b_triggers, b_folders)
                    a_sum = extract_entity_summary(kind, a_item, a_triggers, a_folders)
                    changed.append({
                        "kind": kind,
                        "id": eid,
                        "name": a_sum["name"],
                        "beforeName": b_sum["name"],
                        "type": a_sum["type"],
                        "pausedBefore": b_sum["paused"],
                        "pausedAfter": a_sum["paused"],
                        "folderName": a_sum["folderName"],
                        "firingTriggers": a_sum["firingTriggers"],
                        "blockingTriggers": a_sum["blockingTriggers"],
                        "fieldChanges": field_changes,
                        "codeDiff": code_diff,
                    })

        for eid in sorted(b_map.keys()):
            if eid not in a_map:
                b_item = b_map[eid]
                summary = extract_entity_summary(kind, b_item, b_triggers, b_folders)
                code_info = extract_code_payload(kind, b_item)
                removed.append({
                    **summary,
                    "parameters": extract_parameter_map(b_item),
                    "code": code_info[0] if code_info else None,
                    "item": strip_noise(b_item, include_metadata=include_metadata),
                })

    added.sort(key=lambda x: (x["kind"], x["id"], x["name"]))
    removed.sort(key=lambda x: (x["kind"], x["id"], x["name"]))
    changed.sort(key=lambda x: (x["kind"], x["id"], x["name"]))

    return {
        "summary": {
            "accountId": str(after.get("accountId") or before.get("accountId") or ""),
            "containerId": str(after.get("containerId") or before.get("containerId") or ""),
            "fromVersion": str(before.get("containerVersionId") or ""),
            "toVersion": str(after.get("containerVersionId") or ""),
            "fromName": str(before.get("name") or ""),
            "toName": str(after.get("name") or ""),
            "fromTimestampUtc": fingerprint_to_utc(before.get("fingerprint")),
            "toTimestampUtc": fingerprint_to_utc(after.get("fingerprint")),
            "fromDescription": str(before.get("description") or ""),
            "toDescription": str(after.get("description") or ""),
            "addedCount": len(added),
            "removedCount": len(removed),
            "changedCount": len(changed),
        },
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def load_versions_from_dir(versions_dir: Path) -> List[Dict[str, Any]]:
    """Load and numerically sort all GTM container version JSON files in a folder."""
    if not versions_dir.exists() or not versions_dir.is_dir():
        raise FileNotFoundError(f"Versions directory does not exist: {versions_dir}")

    ignored_names = {
        "versions_index.json",
        "diff_series.json",
        "manifest.json",
    }
    loaded: Dict[int, Dict[str, Any]] = {}
    for json_path in sorted(versions_dir.glob("*.json")):
        if json_path.name in ignored_names:
            continue
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not is_container_version_payload(raw):
            continue
        ver = unwrap_container_version(raw)
        vid_raw = str(ver.get("containerVersionId") or "").strip()
        if not vid_raw.isdigit():
            continue
        vid = int(vid_raw)
        loaded[vid] = ver

    return [loaded[k] for k in sorted(loaded.keys())]


def write_unpacked_version(ver: Dict[str, Any], target_dir: Path, clean: bool = True) -> Path:
    """Write normalized, key-sorted JSON + extracted HTML/JS/TPL files for one version."""
    ver = unwrap_container_version(ver)
    if clean and target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    triggers_by_id, folders_by_id = _build_lookup_maps(ver)
    vid = str(ver.get("containerVersionId") or "")
    manifest = {
        "accountId": str(ver.get("accountId") or ""),
        "containerId": str(ver.get("containerId") or ""),
        "publicId": ((ver.get("container") or {}).get("publicId") or ""),
        "containerName": ((ver.get("container") or {}).get("name") or ""),
        "containerVersionId": vid,
        "name": str(ver.get("name") or ""),
        "description": str(ver.get("description") or ""),
        "fingerprint": str(ver.get("fingerprint") or ""),
        "timestampUtc": fingerprint_to_utc(ver.get("fingerprint")),
        "counts": {kind: len(ver.get(api_key, []) or []) for api_key, kind, _ in RESOURCE_SPECS if ver.get(api_key)},
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    if isinstance(ver.get("container"), dict):
        (target_dir / "container.json").write_text(
            json.dumps(strip_noise(ver["container"]), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    for api_key, kind, _ in RESOURCE_SPECS:
        items = ver.get(api_key, []) or []
        if not items:
            continue
        if kind == "builtInVariables":
            cleaned_bivs = [strip_noise(x) for x in sorted(items, key=lambda r: get_resource_id(kind, r)) if isinstance(x, dict)]
            (target_dir / "built_in_variables.json").write_text(
                json.dumps(cleaned_bivs, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            continue

        subdir = target_dir / ("templates" if kind == "customTemplates" else kind)
        subdir.mkdir(parents=True, exist_ok=True)
        for item in sorted(items, key=lambda r: get_resource_id(kind, r)):
            if not isinstance(item, dict):
                continue
            eid = get_resource_id(kind, item)
            name = str(item.get("name") or eid)
            stem = f"{safe_slug(eid, 24)}__{safe_slug(name, 56)}"
            cleaned = strip_noise(item)
            enriched_json = dict(cleaned)
            # Add readable resolved hints in unpacked file without changing source fields
            code_info = extract_code_payload(kind, item)
            if code_info:
                code_text, ext = code_info
                (subdir / f"{stem}{ext}").write_text(code_text + ("\n" if not code_text.endswith("\n") else ""), encoding="utf-8")
            if kind == "tags":
                meta_links = {}
                if item.get("firingTriggerId"):
                    meta_links["firingTriggerNames"] = resolve_trigger_names(item.get("firingTriggerId"), triggers_by_id)
                if item.get("blockingTriggerId"):
                    meta_links["blockingTriggerNames"] = resolve_trigger_names(item.get("blockingTriggerId"), triggers_by_id)
                if item.get("parentFolderId") and str(item["parentFolderId"]) in folders_by_id:
                    meta_links["parentFolderName"] = folders_by_id[str(item["parentFolderId"])]
                if meta_links:
                    enriched_json["_resolved"] = meta_links
            (subdir / f"{stem}.json").write_text(
                json.dumps(enriched_json, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    return target_dir


def _run_git(cwd: Path, args: Sequence[str], env: Optional[Dict[str, str]] = None) -> str:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def replay_versions_to_git(versions: List[Dict[str, Any]], git_repo_dir: Path) -> Dict[str, Any]:
    """Replay chronological container versions into a dedicated standalone private Git repository."""
    if not versions:
        raise ValueError("No container versions supplied for git replay")
    resolved = git_repo_dir.expanduser().resolve()
    assert_safe_git_repo(resolved)
    resolved.mkdir(parents=True, exist_ok=True)

    # Reinitialize cleanly if existing branch tags conflict or partial state is detected
    existing_tags: set[str] = set()
    if not (resolved / ".git").exists():
        subprocess.run(["git", "init", "-b", "main", str(resolved)], capture_output=True, check=True)
    else:
        raw_tags = _run_git(resolved, ["tag", "--list"])
        existing_tags = {line.strip() for line in raw_tags.splitlines() if line.strip()}

    if not _git_output(resolved, "config", "--get", "user.name"):
        _run_git(resolved, ["config", "user.name", "GTM History Archiver"])
    if not _git_output(resolved, "config", "--get", "user.email"):
        _run_git(resolved, ["config", "user.email", "gtm-history@local.invalid"])

    pad = max(2, len(str(max(int(v["containerVersionId"]) for v in versions))))
    committed = 0
    skipped = 0

    for idx, ver in enumerate(versions):
        vid = int(ver["containerVersionId"])
        tag_name = f"v{vid:0{pad}d}"
        if tag_name in existing_tags:
            skipped += 1
            continue

        # Wipe working tree entries except .git before unpacking this version
        for child in list(resolved.iterdir()):
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        write_unpacked_version(ver, resolved, clean=False)
        _run_git(resolved, ["add", "-A"])

        iso_date = fingerprint_to_iso(ver.get("fingerprint")) or f"2023-01-01T00:{idx % 60:02d}:00Z"
        title = str(ver.get("name") or f"Container version {vid}").strip()
        desc = str(ver.get("description") or "").strip()
        subject = f"{tag_name}: {title}"
        commit_msg = f"{subject}\n\n{desc}" if desc else subject
        env = {
            "GIT_AUTHOR_DATE": iso_date,
            "GIT_COMMITTER_DATE": iso_date,
        }
        _run_git(resolved, ["commit", "--allow-empty", "-m", commit_msg], env=env)
        _run_git(resolved, ["tag", "-f", tag_name])
        committed += 1

    return {
        "gitRepo": str(resolved),
        "totalVersions": len(versions),
        "committed": committed,
        "skippedExisting": skipped,
        "latestTag": f"v{int(versions[-1]['containerVersionId']):0{pad}d}",
    }


def extract_vendor_domains_ledger(ver: Dict[str, Any]) -> List[Dict[str, Any]]:
    ver = unwrap_container_version(ver)
    rows: List[Dict[str, Any]] = []
    for tag in sorted(ver.get("tag", []) or [], key=lambda x: str(x.get("tagId") or "")):
        if not isinstance(tag, dict):
            continue
        code_info = extract_code_payload("tags", tag)
        if not code_info:
            continue
        domains = extract_domains_from_html(code_info[0])
        if not domains:
            continue
        rows.append({
            "tagId": str(tag.get("tagId") or ""),
            "tagName": str(tag.get("name") or ""),
            "paused": bool(tag.get("paused", False)),
            "domains": [{"domain": d, "classification": classify_domain(d)} for d in domains],
        })
    return rows


def build_entity_store_and_series(versions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Construct compact content-addressed store + full chronological transition ledger."""
    if not versions:
        raise ValueError("No container versions loaded")

    latest = versions[-1]
    container_obj = latest.get("container") if isinstance(latest.get("container"), dict) else {}
    container_meta = {
        "accountId": str(latest.get("accountId") or container_obj.get("accountId") or ""),
        "containerId": str(latest.get("containerId") or container_obj.get("containerId") or ""),
        "publicId": str(container_obj.get("publicId") or ""),
        "containerName": str(container_obj.get("name") or f"Container {latest.get('containerId') or ''}"),
        "totalVersions": len(versions),
        "latestVersion": int(latest.get("containerVersionId") or 0),
        "latestVersionName": str(latest.get("name") or ""),
        "latestTimestampUtc": fingerprint_to_utc(latest.get("fingerprint")),
        "latestCounts": {kind: len(latest.get(api_key, []) or []) for api_key, kind, _ in RESOURCE_SPECS},
        "activeTags": sum(1 for t in (latest.get("tag", []) or []) if isinstance(t, dict) and not t.get("paused", False)),
        "pausedTags": sum(1 for t in (latest.get("tag", []) or []) if isinstance(t, dict) and t.get("paused", False)),
    }

    blobs: Dict[str, str] = {}
    entities: Dict[str, Dict[str, Any]] = {}
    version_records: List[Dict[str, Any]] = []
    transitions: List[Dict[str, Any]] = []

    for idx, ver in enumerate(versions):
        vid = int(ver.get("containerVersionId") or 0)
        refs: Dict[str, List[str]] = {}
        counts: Dict[str, int] = {}

        for api_key, kind, _ in RESOURCE_SPECS:
            raw_items = ver.get(api_key, []) or []
            kind_hashes: List[str] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                cleaned = strip_noise(item)
                if kind == "customTemplates" and isinstance(cleaned.get("templateData"), str):
                    tpl_raw = cleaned["templateData"]
                    tpl_hash = hashlib.sha256(tpl_raw.encode("utf-8")).hexdigest()[:12]
                    if tpl_hash not in blobs:
                        blobs[tpl_hash] = tpl_raw
                    cleaned = dict(cleaned)
                    cleaned["templateDataHash"] = tpl_hash
                    del cleaned["templateData"]
                canonical = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                ehash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:14]
                if ehash not in entities:
                    entities[ehash] = cleaned
                kind_hashes.append(ehash)
            refs[kind] = kind_hashes
            counts[kind] = len(kind_hashes)

        delta_summary = {"added": 0, "removed": 0, "changed": 0}
        if idx > 0:
            diff_obj = diff_versions(versions[idx - 1], ver)
            delta_summary = {
                "added": diff_obj["summary"]["addedCount"],
                "removed": diff_obj["summary"]["removedCount"],
                "changed": diff_obj["summary"]["changedCount"],
            }
            transitions.append(diff_obj)

        version_records.append({
            "versionId": vid,
            "name": str(ver.get("name") or ""),
            "description": str(ver.get("description") or ""),
            "fingerprint": str(ver.get("fingerprint") or ""),
            "timestampUtc": fingerprint_to_utc(ver.get("fingerprint")),
            "counts": counts,
            "deltaFromPrev": delta_summary,
            "refs": refs,
        })

    return {
        "schemaVersion": "gtm-history-bundle/1",
        "generatedAtUtc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "container": container_meta,
        "vendorDomainsLatest": extract_vendor_domains_ledger(latest),
        "versions": version_records,
        "transitions": transitions,
        "entities": entities,
        "blobs": blobs,
    }


def render_changelog_markdown(bundle: Dict[str, Any]) -> str:
    meta = bundle["container"]
    versions = bundle["versions"]
    transitions_by_to = {int(t["summary"]["toVersion"]): t for t in bundle["transitions"]}
    vendor_rows = bundle.get("vendorDomainsLatest", [])

    lines: List[str] = []
    lines.append(f"# GTM Container Version History: {meta['containerName']} ({meta['publicId']})")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(f"- Account ID: `{meta['accountId']}`")
    lines.append(f"- Container ID: `{meta['containerId']}`")
    lines.append(f"- Public ID: `{meta['publicId']}`")
    lines.append(f"- Archived Versions: `{meta['totalVersions']}` (`v{versions[0]['versionId']}` to `v{meta['latestVersion']}`)")
    lines.append(f"- Latest Live Version: `v{meta['latestVersion']}` ({meta['latestTimestampUtc'] or 'timestamp unavailable'})")
    lines.append(
        f"- Active Snapshot Resources: `{meta['latestCounts'].get('tags', 0)}` tags "
        f"({meta['activeTags']} active, {meta['pausedTags']} paused), "
        f"`{meta['latestCounts'].get('triggers', 0)}` triggers, "
        f"`{meta['latestCounts'].get('variables', 0)}` variables, "
        f"`{meta['latestCounts'].get('customTemplates', 0)}` templates, "
        f"`{meta['latestCounts'].get('folders', 0)}` folders"
    )
    lines.append("")

    if vendor_rows:
        lines.append("## Latest Custom HTML External Domains")
        lines.append("")
        lines.append("| Tag ID | Tag Name | State | Domains | Classification |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for row in vendor_rows:
            state = "Paused" if row["paused"] else "Active"
            doms = ", ".join(d["domain"] for d in row["domains"])
            classes = ", ".join(sorted({d["classification"] for d in row["domains"]}))
            lines.append(f"| `{row['tagId']}` | {row['tagName']} | {state} | `{doms}` | {classes} |")
        lines.append("")

    lines.append("## Chronological Version Index")
    lines.append("")
    lines.append("| Version | Timestamp UTC | Title | Added | Changed | Removed | Tags | Triggers | Variables |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for v in reversed(versions):
        d = v["deltaFromPrev"]
        title = (v["name"] or "-").replace("|", "\\|")
        ts = v["timestampUtc"] or "-"
        c = v["counts"]
        lines.append(
            f"| `v{v['versionId']:02d}` | {ts} | {title} | +{d['added']} | ~{d['changed']} | -{d['removed']} | "
            f"{c.get('tags', 0)} | {c.get('triggers', 0)} | {c.get('variables', 0)} |"
        )
    lines.append("")

    lines.append("## Detailed Version Diffs")
    lines.append("")
    for v in reversed(versions):
        vid = v["versionId"]
        title = v["name"] or "Untitled version"
        ts = v["timestampUtc"] or "unknown time"
        lines.append(f"### v{vid:02d} — {title} ({ts})")
        lines.append("")
        if v["description"]:
            for dline in v["description"].splitlines():
                lines.append(f"> {dline}")
            lines.append("")
        tr = transitions_by_to.get(vid)
        if not tr:
            lines.append("Initial archived container baseline.")
            lines.append("")
            continue
        s = tr["summary"]
        if s["addedCount"] == 0 and s["removedCount"] == 0 and s["changedCount"] == 0:
            lines.append("No semantic resource differences detected compared to previous version.")
            lines.append("")
            continue

        lines.append(f"Delta from `v{s['fromVersion']}`: `+{s['addedCount']}` added, `~{s['changedCount']}` modified, `-{s['removedCount']}` removed.")
        lines.append("")

        if tr["added"]:
            lines.append("#### Added Resources")
            lines.append("")
            for item in tr["added"]:
                triggers_txt = f" | firing: {', '.join(item['firingTriggers'])}" if item["firingTriggers"] else ""
                lines.append(f"- `[{item['kind']}]` `{item['id']}` **{item['name']}** (`{item['type']}`{triggers_txt})")
            lines.append("")

        if tr["removed"]:
            lines.append("#### Removed Resources")
            lines.append("")
            for item in tr["removed"]:
                lines.append(f"- `[{item['kind']}]` `{item['id']}` **{item['name']}** (`{item['type']}`)")
            lines.append("")

        if tr["changed"]:
            lines.append("#### Modified Resources")
            lines.append("")
            for ch in tr["changed"]:
                lines.append(f"- `[{ch['kind']}]` `{ch['id']}` **{ch['name']}** (`{ch['type']}`)")
                for fc in ch["fieldChanges"]:
                    b_repr = json.dumps(fc["before"], ensure_ascii=False)
                    a_repr = json.dumps(fc["after"], ensure_ascii=False)
                    if len(b_repr) > 120:
                        b_repr = b_repr[:117] + "..."
                    if len(a_repr) > 120:
                        a_repr = a_repr[:117] + "..."
                    lines.append(f"  - `{fc['field']}`: `{b_repr}` -> `{a_repr}`")
                if ch.get("codeDiff"):
                    diff_preview = ch["codeDiff"][:80]
                    lines.append("")
                    lines.append("```diff")
                    lines.extend(diff_preview)
                    if len(ch["codeDiff"]) > 80:
                        lines.append(f"... ({len(ch['codeDiff']) - 80} more lines truncated; inspect full diff in viewer UI)")
                    lines.append("```")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_viewer_html(bundle: Dict[str, Any]) -> str:
    if not VIEWER_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Missing HTML viewer template: {VIEWER_TEMPLATE_PATH}")
    template = VIEWER_TEMPLATE_PATH.read_text(encoding="utf-8")
    # Build embedded payload without repeating precomputed transitions to keep viewer compact;
    # the UI uses entities + blobs + version refs to diff ANY vA vs vB dynamically in JS.
    ui_payload = {
        "schemaVersion": bundle["schemaVersion"],
        "generatedAtUtc": bundle["generatedAtUtc"],
        "container": bundle["container"],
        "vendorDomainsLatest": bundle["vendorDomainsLatest"],
        "versions": bundle["versions"],
        "entities": bundle["entities"],
        "blobs": bundle["blobs"],
    }
    raw_json = json.dumps(ui_payload, separators=(",", ":"), ensure_ascii=False)
    # Critical HTML safety: prevent GTM Custom HTML `</script>` strings from closing the JSON tag early!
    safe_json = raw_json.replace("</", "<\\/")
    return template.replace("__GTM_HISTORY_DATA_JSON__", safe_json)


def build_archive_artifacts(
    versions_dir: Path,
    out_dir: Optional[Path] = None,
    write_latest: bool = True,
    write_changelog: bool = True,
    write_diff_series: bool = True,
    build_ui: bool = True,
    refresh_index: bool = True,
    allow_unsafe_out: bool = False,
) -> Dict[str, Any]:
    versions = load_versions_from_dir(versions_dir)
    if not versions:
        raise ValueError(f"No valid GTM ContainerVersion JSON files found in {versions_dir}")

    dest_dir = (out_dir or versions_dir).expanduser().resolve()
    assert_safe_output_dir(dest_dir, allow_unsafe_out=allow_unsafe_out)
    dest_dir.mkdir(parents=True, exist_ok=True)

    bundle = build_entity_store_and_series(versions)
    written: Dict[str, str] = {}

    if refresh_index:
        index_rows = []
        pad = max(2, len(str(bundle["container"]["latestVersion"])))
        for v in bundle["versions"]:
            fname = f"gtm_v{v['versionId']:0{pad}d}.json"
            fpath = versions_dir / fname
            size_kb = round(fpath.stat().st_size / 1024.0, 1) if fpath.exists() else 0.0
            index_rows.append({
                "versionId": v["versionId"],
                "name": v["name"],
                "description": v["description"],
                "timestampUtc": v["timestampUtc"],
                "file": fname,
                "size_kb": size_kb,
                "tags": v["counts"].get("tags", 0),
                "triggers": v["counts"].get("triggers", 0),
                "variables": v["counts"].get("variables", 0),
                "customTemplates": v["counts"].get("customTemplates", 0),
                "folders": v["counts"].get("folders", 0),
            })
        idx_path = dest_dir / "versions_index.json"
        idx_path.write_text(json.dumps(index_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written["versionsIndex"] = str(idx_path)

    if write_diff_series:
        series_payload = {
            "schemaVersion": bundle["schemaVersion"],
            "generatedAtUtc": bundle["generatedAtUtc"],
            "container": bundle["container"],
            "vendorDomainsLatest": bundle["vendorDomainsLatest"],
            "versions": [
                {k: v[k] for k in ("versionId", "name", "description", "fingerprint", "timestampUtc", "counts", "deltaFromPrev")}
                for v in bundle["versions"]
            ],
            "transitions": bundle["transitions"],
        }
        diff_path = dest_dir / "diff_series.json"
        diff_path.write_text(json.dumps(series_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written["diffSeries"] = str(diff_path)

    if write_changelog:
        cl_path = dest_dir / "CHANGELOG.md"
        cl_path.write_text(render_changelog_markdown(bundle), encoding="utf-8")
        written["changelog"] = str(cl_path)

    if write_latest:
        latest_dir = write_unpacked_version(versions[-1], dest_dir / "latest", clean=True)
        written["latestUnpacked"] = str(latest_dir)

    if build_ui:
        html_path = dest_dir / "history_viewer.html"
        html_path.write_text(render_viewer_html(bundle), encoding="utf-8")
        written["historyViewerHtml"] = str(html_path)

    return {
        "versionsDir": str(versions_dir.resolve()),
        "outDir": str(dest_dir),
        "container": bundle["container"],
        "written": written,
    }


def _parse_version_range(spec: Optional[str], available_ids: List[int]) -> List[int]:
    if not spec or spec.strip().lower() == "all":
        return available_ids
    selected: set[int] = set()
    avail_set = set(available_ids)
    for part in spec.split(","):
        p = part.strip()
        if not p:
            continue
        if "-" in p:
            lo_s, hi_s = p.split("-", 1)
            lo = int(lo_s.strip())
            hi = int(hi_s.strip())
            for vid in range(min(lo, hi), max(lo, hi) + 1):
                if vid in avail_set:
                    selected.add(vid)
        else:
            vid = int(p)
            if vid in avail_set:
                selected.add(vid)
    return sorted(selected)


def archive_remote_container(
    account_id: str,
    container_id: str,
    out_dir: Path,
    version_range: Optional[str] = None,
    refresh: bool = False,
    allow_unsafe_out: bool = False,
    cli_runner: Callable[[str], Any] = run_gtm_cli,
) -> Dict[str, Any]:
    """Read-only download and cache of GTM container version JSON history."""
    _ensure_local_bin_in_path()
    acc = validate_numeric_id(account_id, "accountId")
    cnt = validate_numeric_id(container_id, "containerId")
    dest = out_dir.expanduser().resolve()
    assert_safe_output_dir(dest, allow_unsafe_out=allow_unsafe_out)
    dest.mkdir(parents=True, exist_ok=True)

    headers = cli_runner(
        f"version-headers list --account-id {acc} --container-id {cnt} --output json"
    )
    if not isinstance(headers, list):
        raise RuntimeError(f"Failed to list version headers for {acc}/{cnt}: {headers}")

    all_ids = sorted(
        int(h["containerVersionId"])
        for h in headers
        if isinstance(h, dict) and str(h.get("containerVersionId", "")).isdigit()
    )
    if not all_ids:
        raise RuntimeError(f"Container {acc}/{cnt} returned zero version headers")

    target_ids = _parse_version_range(version_range, all_ids)
    pad = max(2, len(str(max(all_ids))))
    downloaded = 0
    cached = 0
    failed: List[Dict[str, Any]] = []

    for vid in target_ids:
        fpath = dest / f"gtm_v{vid:0{pad}d}.json"
        if not refresh and fpath.exists():
            try:
                existing = json.loads(fpath.read_text(encoding="utf-8"))
                if is_container_version_payload(existing) and str(unwrap_container_version(existing).get("containerVersionId")) == str(vid):
                    cached += 1
                    continue
            except Exception:
                pass

        payload = cli_runner(
            f"versions get --account-id {acc} --container-id {cnt} --version-id {vid} --output json"
        )
        if not isinstance(payload, dict) or "error" in payload or not is_container_version_payload(payload):
            failed.append({"versionId": vid, "error": payload})
            continue

        fpath.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        downloaded += 1

    if failed:
        raise RuntimeError(f"Failed downloading {len(failed)} GTM version(s): {failed[:3]}")

    return {
        "accountId": acc,
        "containerId": cnt,
        "outDir": str(dest),
        "totalHeaders": len(all_ids),
        "targetVersions": len(target_ids),
        "downloaded": downloaded,
        "cached": cached,
    }


def search_archive(
    versions: List[Dict[str, Any]],
    query: str,
    version_scope: str = "latest",
    kind_filter: str = "all",
) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return []

    target_versions = [versions[-1]] if version_scope == "latest" else list(reversed(versions))
    matches: List[Dict[str, Any]] = []

    for ver in target_versions:
        vid = int(ver.get("containerVersionId") or 0)
        triggers_by_id, folders_by_id = _build_lookup_maps(ver)
        for api_key, kind, _ in RESOURCE_SPECS:
            if kind_filter != "all" and kind != kind_filter:
                continue
            for item in ver.get(api_key, []) or []:
                if not isinstance(item, dict):
                    continue
                serialized = json.dumps(strip_noise(item), ensure_ascii=False).lower()
                if q in serialized:
                    summary = extract_entity_summary(kind, item, triggers_by_id, folders_by_id)
                    code_info = extract_code_payload(kind, item)
                    snippet = ""
                    if code_info:
                        for line in code_info[0].splitlines():
                            if q in line.lower():
                                snippet = line.strip()[:180]
                                break
                    matches.append({
                        "versionId": vid,
                        "versionName": str(ver.get("name") or ""),
                        "timestampUtc": fingerprint_to_utc(ver.get("fingerprint")),
                        **summary,
                        "matchSnippet": snippet,
                    })
                    if len(matches) >= 250:
                        return matches
    return matches


def trace_entity_lifecycle(versions: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Trace every version transition where a matching ID, resource name, or domain changed."""
    q = query.strip().lower()
    if not q:
        return []

    events: List[Dict[str, Any]] = []
    # Check baseline existence in first version
    first = versions[0]
    for api_key, kind, _ in RESOURCE_SPECS:
        for item in first.get(api_key, []) or []:
            if isinstance(item, dict) and q in json.dumps(strip_noise(item), ensure_ascii=False).lower():
                events.append({
                    "versionId": int(first["containerVersionId"]),
                    "timestampUtc": fingerprint_to_utc(first.get("fingerprint")),
                    "event": "present_in_baseline",
                    "kind": kind,
                    "id": get_resource_id(kind, item),
                    "name": str(item.get("name") or ""),
                    "paused": bool(item.get("paused", False)),
                })

    for idx in range(1, len(versions)):
        d = diff_versions(versions[idx - 1], versions[idx])
        s = d["summary"]
        for bucket, label in (("added", "added"), ("removed", "removed")):
            for item in d[bucket]:
                if q in json.dumps(item, ensure_ascii=False).lower():
                    events.append({
                        "versionId": int(s["toVersion"]),
                        "timestampUtc": s["toTimestampUtc"],
                        "event": label,
                        "kind": item["kind"],
                        "id": item["id"],
                        "name": item["name"],
                        "paused": item.get("paused", False),
                    })
        for ch in d["changed"]:
            if q in json.dumps(ch, ensure_ascii=False).lower():
                events.append({
                    "versionId": int(s["toVersion"]),
                    "timestampUtc": s["toTimestampUtc"],
                    "event": "modified",
                    "kind": ch["kind"],
                    "id": ch["id"],
                    "name": ch["name"],
                    "fieldChanges": ch["fieldChanges"],
                })
    return events


def serve_explorer(versions_dir: Path, host: str = "127.0.0.1", port: int = 9475) -> None:
    versions = load_versions_from_dir(versions_dir)
    if not versions:
        raise ValueError(f"No container versions found in {versions_dir}")
    bundle = build_entity_store_and_series(versions)
    html_content = render_viewer_html(bundle).encode("utf-8")
    ver_map = {str(v.get("containerVersionId")): v for v in versions}

    class ExplorerHandler(http.server.BaseHTTPRequestHandler):
        def _send_json(self, code: int, data: Any) -> None:
            body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if route in ("/", "/timeline", "/compare", "/search", "/inspector"):
                self._send_html(200, html_content)
                return

            if route == "/api/overview":
                self._send_json(200, {
                    "container": bundle["container"],
                    "vendorDomainsLatest": bundle["vendorDomainsLatest"],
                    "noiseKeysExcluded": sorted(NOISE_KEYS),
                    "resourceKinds": [kind for _, kind, _ in RESOURCE_SPECS],
                })
                return

            if route == "/api/diff":
                v_from = (qs.get("from") or [""])[0]
                v_to = (qs.get("to") or [""])[0]
                include_meta = (qs.get("include_metadata") or ["0"])[0] in ("1", "true", "yes")
                if v_from not in ver_map or v_to not in ver_map:
                    self._send_json(400, {"error": f"Unknown version pair: {v_from!r} -> {v_to!r}"})
                    return
                self._send_json(200, diff_versions(ver_map[v_from], ver_map[v_to], include_metadata=include_meta))
                return

            if route == "/api/search":
                q = (qs.get("q") or [""])[0]
                scope = (qs.get("version") or ["latest"])[0]
                kind = (qs.get("kind") or ["all"])[0]
                results = search_archive(versions, q, version_scope=scope, kind_filter=kind)
                self._send_json(200, {"query": q, "scope": scope, "count": len(results), "results": results})
                return

            if route == "/api/trace":
                q = (qs.get("q") or [""])[0]
                events = trace_entity_lifecycle(versions, q)
                self._send_json(200, {"query": q, "count": len(events), "events": events})
                return

            # Any unknown browser path returns SPA root cleanly rather than 404
            self._send_html(200, html_content)

    class ReusableTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with ReusableTCPServer((host, port), ExplorerHandler) as httpd:
        print(
            json.dumps(
                {
                    "status": "serving",
                    "url": f"http://{host}:{port}/timeline",
                    "container": bundle["container"]["publicId"],
                    "versions": bundle["container"]["totalVersions"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gtm-agent history",
        description="Archive, unpack, diff, git-replay, and visualize GTM container version history",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # 1. archive
    p_arch = sub.add_parser("archive", help="Read-only download of GTM versions via upstream gtm CLI")
    p_arch.add_argument("--account-id", required=True, help="GTM account ID")
    p_arch.add_argument("--container-id", required=True, help="GTM container ID")
    p_arch.add_argument("--out", required=True, help="Private directory for archived version JSONs")
    p_arch.add_argument("--versions", help="Version filter (e.g. 1-57 or 50,56,57; default: all)")
    p_arch.add_argument("--refresh", action="store_true", help="Re-download existing version JSONs")
    p_arch.add_argument("--unpack", action="store_true", help="Generate latest/ unpacked tree, CHANGELOG.md, diff_series.json")
    p_arch.add_argument("--ui", action="store_true", help="Generate interactive history_viewer.html")
    p_arch.add_argument("--git-repo", help="Optional external private Git repo directory to replay chronological commits")
    p_arch.add_argument("--allow-unsafe-out", action="store_true", help="Override public repo safety guard")
    p_arch.add_argument("--json", action="store_true", help="Output JSON")

    # 2. build (offline-first unpack + diff series + CHANGELOG + HTML UI)
    p_build = sub.add_parser("build", help="Unpack, compute full diff series, CHANGELOG.md, and UI viewer from version JSONs")
    p_build.add_argument("--dir", required=True, help="Directory containing gtm_v*.json container version files")
    p_build.add_argument("--out", help="Output directory (defaults to --dir)")
    p_build.add_argument("--git-repo", help="Optional standalone private Git repo directory for chronological commit replay")
    p_build.add_argument("--no-latest", action="store_true", help="Skip writing unpacked latest/ tree")
    p_build.add_argument("--no-changelog", action="store_true", help="Skip writing CHANGELOG.md")
    p_build.add_argument("--no-diff-series", action="store_true", help="Skip writing diff_series.json")
    p_build.add_argument("--no-ui", action="store_true", help="Skip writing history_viewer.html")
    p_build.add_argument("--allow-unsafe-out", action="store_true", help="Override public repo safety guard")
    p_build.add_argument("--json", action="store_true", help="Output JSON")

    # 3. diff
    p_diff = sub.add_parser("diff", help="Compute semantic and unified code diff between two container versions")
    p_diff.add_argument("--dir", help="Archive directory containing gtm_v*.json files")
    p_diff.add_argument("--from", dest="v_from", help="Source version ID (with --dir) or JSON file path")
    p_diff.add_argument("--to", dest="v_to", help="Target version ID (with --dir) or JSON file path")
    p_diff.add_argument("--include-metadata", action="store_true", help="Include fingerprint/path metadata differences")
    p_diff.add_argument("--json", action="store_true", help="Output JSON")

    # 4. git-replay
    p_git = sub.add_parser("git-replay", help="Replay version JSONs into an isolated private Git repository")
    p_git.add_argument("--dir", required=True, help="Directory containing gtm_v*.json files")
    p_git.add_argument("--git-repo", required=True, help="Standalone private Git repo directory (outside tracked repos)")
    p_git.add_argument("--json", action="store_true", help="Output JSON")

    # 5. serve
    p_serve = sub.add_parser("serve", help="Serve the interactive Change Explorer UI and live diagnostic endpoints")
    p_serve.add_argument("--dir", required=True, help="Directory containing archived gtm_v*.json files")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=9475, help="HTTP port (default: 9475)")

    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 0

    try:
        if args.subcommand == "archive":
            out_path = Path(args.out)
            res: Dict[str, Any] = archive_remote_container(
                account_id=args.account_id,
                container_id=args.container_id,
                out_dir=out_path,
                version_range=args.versions,
                refresh=args.refresh,
                allow_unsafe_out=args.allow_unsafe_out,
            )
            if args.unpack or args.ui:
                built = build_archive_artifacts(
                    versions_dir=out_path,
                    out_dir=out_path,
                    write_latest=bool(args.unpack),
                    write_changelog=bool(args.unpack),
                    write_diff_series=bool(args.unpack),
                    build_ui=bool(args.ui or args.unpack),
                    allow_unsafe_out=args.allow_unsafe_out,
                )
                res["artifacts"] = built["written"]
            if args.git_repo:
                vers = load_versions_from_dir(out_path)
                res["gitReplay"] = replay_versions_to_git(vers, Path(args.git_repo))
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0

        if args.subcommand == "build":
            vdir = Path(args.dir)
            odir = Path(args.out) if args.out else vdir
            res = build_archive_artifacts(
                versions_dir=vdir,
                out_dir=odir,
                write_latest=not args.no_latest,
                write_changelog=not args.no_changelog,
                write_diff_series=not args.no_diff_series,
                build_ui=not args.no_ui,
                allow_unsafe_out=args.allow_unsafe_out,
            )
            if args.git_repo:
                vers = load_versions_from_dir(vdir)
                res["gitReplay"] = replay_versions_to_git(vers, Path(args.git_repo))
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0

        if args.subcommand == "diff":
            if args.dir:
                vers = {str(v["containerVersionId"]): v for v in load_versions_from_dir(Path(args.dir))}
                if not args.v_from or not args.v_to:
                    raise ValueError("--from and --to are required with --dir")
                if args.v_from not in vers or args.v_to not in vers:
                    raise ValueError(f"Version not found in {args.dir}: from={args.v_from}, to={args.v_to}")
                b_ver, a_ver = vers[args.v_from], vers[args.v_to]
            else:
                if not args.v_from or not args.v_to:
                    raise ValueError("--from and --to file paths are required")
                b_ver = json.loads(Path(args.v_from).read_text(encoding="utf-8"))
                a_ver = json.loads(Path(args.v_to).read_text(encoding="utf-8"))
            d = diff_versions(b_ver, a_ver, include_metadata=args.include_metadata)
            if args.json:
                print(json.dumps(d, indent=2, ensure_ascii=False))
            else:
                s = d["summary"]
                print(f"v{s['fromVersion']} -> v{s['toVersion']} ({s['toName']}): +{s['addedCount']} added, ~{s['changedCount']} changed, -{s['removedCount']} removed")
                for x in d["added"]:
                    print(f"  + [{x['kind']}] {x['id']} {x['name']} ({x['type']})")
                for x in d["removed"]:
                    print(f"  - [{x['kind']}] {x['id']} {x['name']} ({x['type']})")
                for x in d["changed"]:
                    fields = ", ".join(fc["field"] for fc in x["fieldChanges"])
                    print(f"  ~ [{x['kind']}] {x['id']} {x['name']} ({fields})")
            return 0

        if args.subcommand == "git-replay":
            vers = load_versions_from_dir(Path(args.dir))
            res = replay_versions_to_git(vers, Path(args.git_repo))
            print(json.dumps(res, indent=2, ensure_ascii=False))
            return 0

        if args.subcommand == "serve":
            serve_explorer(Path(args.dir), host=args.host, port=args.port)
            return 0

    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
