#!/usr/bin/env python3
"""Render a disk_scan plan as an inert, local Markdown decision report.

CLI: --plan PLAN.json --output NEW.md [--language zh|en] [--choices CHOICES.json]
     [--applications INVENTORY.json]
Only supplied JSON input files and the requested output are accessed. Paths
listed inside JSON are data: they are never opened, checked or acted upon.

Optional choices have this strict schema (no additional keys):
{"schema_version": 1, "scenarios": [
  {"name": "conservative", "choices": [
    {"path": "<exact file candidate path>", "action": "copy_then_release",
     "explanation": "Why this is proposed", "consequence": "What may be lost",
     "destination_volume_id": "<user-declared, unverified volume ID>"}
  ]}
]}
One or two scenarios may be named conservative/expanded, once each. Each has at
most 1000 choices. Actions: keep, copy_then_release, app_cleanup, review.
Explanation and consequence are required for all non-review actions; review
may omit them. Only copy_then_release accepts destination_volume_id; omission
means unresolved destination and contributes zero to the hypothetical scope.
Duplicate path aliases and paths outside the exact file candidate list fail.

Scenario arithmetic describes selected LOGICAL FILE SCOPE, never physical free
space or goal achievement. Only ordinary single-link candidates attributed to
the known goal volume and a different declared destination are counted. System,
application/cache, hard-linked and unknown-volume files contribute zero. The
destination declaration is NOT verification, approval or an execution request.
Unselected candidates have no proposed action; consent is never inferred.

Public API: load_json, render_report, analyze_scenarios, write_report, main.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata

import disk_scan as scanner
import app_inventory as inventory_tools

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_TEXT = 2000
MAX_PATH = 4096
MAX_ITEMS = 1000
MAX_APPLICATION_MATCHES_SHOWN = 3
MAX_INTEGER = 2**63 - 1
CATEGORIES = {"user_file", "downloads", "archive_or_installer", "possible_temp_or_cache", "application_data", "system_managed"}
ORDINARY = {"user_file", "downloads", "archive_or_installer"}
PLAN_KEYS = {
    "schema_version", "created_at", "scan_created_at", "scan_incomplete", "goal_bytes", "goal_kind",
    "goal_volume", "baseline_free_bytes", "required_additional_bytes", "capacity_snapshot_status",
    "goal_evaluation", "candidates", "directory_reviews", "candidate_logical_bytes",
    "automatic_reclaimable_bytes", "excluded_system_files", "excluded_other_or_unknown_volume_files", "limitations",
}
FILE_KEYS = {"path", "volume_id", "category", "logical_bytes", "action", "risk", "hardlink_count", "evidence", "estimated_reclaimable_bytes"}
DIRECTORY_KEYS = {"path", "volume_id", "category", "logical_bytes", "observed_files", "hardlinked_files", "deduplicated_file_names",
                  "incomplete", "is_scan_root", "action", "evidence", "estimated_reclaimable_bytes"}


class ReportError(ValueError):
    """The supplied decision input or report path is invalid."""


def _object(value, allowed, required=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or not set(value) <= set(allowed):
        raise ReportError("Unsupported object fields or missing required fields")


def _text(value, limit=MAX_TEXT, *, nullable=False):
    if value is None and nullable:
        return value
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ReportError("Text must be nonempty and within the configured length limit")
    if any((ord(char) < 32 and char not in "\t\r\n") or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ReportError("Unsupported control or surrogate character")
    return value


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise ReportError("Expected a bounded nonnegative integer")
    return value


def _boolean(value):
    if type(value) is not bool:
        raise ReportError("Expected a JSON boolean")
    return value


def _list(value, limit=MAX_ITEMS):
    if not isinstance(value, list) or len(value) > limit:
        raise ReportError("Expected a bounded JSON array")
    return value


def _bounded_tree(value):
    """Also bound callers that pass Python data directly instead of load_json."""
    budget = [0, 0]

    def visit(item, depth):
        budget[0] += 1
        if depth > 16 or budget[0] > 30000:
            raise ReportError("JSON structure is too deep or too large")
        if isinstance(item, str):
            if len(item) > MAX_PATH:
                raise ReportError("JSON string exceeds the path-length limit")
            try:
                budget[1] += len(item.encode("utf-8"))
            except UnicodeError as error:
                raise ReportError("JSON contains an invalid Unicode string") from error
            if budget[1] > MAX_INPUT_BYTES:
                raise ReportError("JSON text exceeds the input budget")
        elif isinstance(item, dict):
            if len(item) > 64 or not all(isinstance(key, str) for key in item):
                raise ReportError("Invalid JSON object")
            for key, child in item.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, list):
            _list(item)
            for child in item:
                visit(child, depth + 1)
        elif item is not None and type(item) not in (int, bool):
            raise ReportError("Unsupported JSON value type")

    visit(value, 0)


def _path_data(value):
    _text(value, MAX_PATH)
    if not (value.startswith(("/", "\\\\")) or re.match(r"^[a-zA-Z]:[\\/]", value)):
        raise ReportError("Candidate paths must be absolute strings from the scan plan")
    return value


def _validate_volume(volume):
    if volume is None:
        return
    _object(volume, {"volume_id", "path", "queried_at", "sampled_at", "scan_roots", "free_bytes", "total_bytes", "used_bytes"},
            {"volume_id", "free_bytes"})
    _text(volume["volume_id"], 256)
    _integer(volume["free_bytes"])
    for key in ("total_bytes", "used_bytes"):
        if key in volume:
            _integer(volume[key])
    if "total_bytes" in volume and (volume["free_bytes"] > volume["total_bytes"] or volume.get("used_bytes", 0) > volume["total_bytes"]):
        raise ReportError("Inconsistent volume capacity snapshot")
    for key in ("path", "queried_at"):
        if key in volume:
            _path_data(volume[key])
    if "sampled_at" in volume:
        _text(volume["sampled_at"], 256)
    if "scan_roots" in volume:
        for value in _list(volume["scan_roots"], 64):
            _path_data(value)


def _validate_entries(entries, directory=False):
    seen = set()
    for item in _list(entries):
        required = {"path", "logical_bytes", "category"} | ({"observed_files"} if directory else {"hardlink_count"})
        _object(item, DIRECTORY_KEYS if directory else FILE_KEYS, required)
        path = _path_data(item["path"])
        key = scanner.path_key(path)
        if key in seen:
            raise ReportError("Duplicate or aliased candidate path")
        seen.add(key)
        _integer(item["logical_bytes"])
        _text(item["category"], 256)
        if item["category"] not in CATEGORIES:
            raise ReportError("Unknown candidate category")
        _text(item.get("volume_id"), 256, nullable=True)
        if directory:
            _integer(item["observed_files"])
            for field in ("hardlinked_files", "deduplicated_file_names"):
                if field in item:
                    _integer(item[field])
            for field in ("incomplete", "is_scan_root"):
                if field in item:
                    _boolean(item[field])
        else:
            _integer(item["hardlink_count"], 1)
        for field in ("risk", "action"):
            if field in item:
                _text(item[field], 256)
        if "evidence" in item:
            for evidence in _list(item["evidence"], 20):
                _text(evidence)
        if item.get("estimated_reclaimable_bytes") is not None:
            raise ReportError("Plan must not provide unverified reclaim estimates")


def validate_plan(plan):
    _bounded_tree(plan)
    _object(plan, PLAN_KEYS, {"schema_version", "goal_kind", "goal_bytes", "scan_incomplete", "candidates"})
    if type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
        raise ReportError("Expected disk_scan decision plan schema_version 1")
    if plan["goal_kind"] not in ("additional_free_space", "target_free_space"):
        raise ReportError("Unsupported goal kind")
    _integer(plan["goal_bytes"], 1)
    _boolean(plan["scan_incomplete"])
    _validate_volume(plan.get("goal_volume"))
    volume = plan.get("goal_volume")
    baseline = volume["free_bytes"] if volume else None
    if plan["goal_kind"] == "target_free_space" and baseline is None:
        raise ReportError("A target-free-space plan needs a selected volume snapshot")
    expected = plan["goal_bytes"] if plan["goal_kind"] == "additional_free_space" else max(plan["goal_bytes"] - baseline, 0)
    if "baseline_free_bytes" in plan:
        if plan["baseline_free_bytes"] is not None:
            _integer(plan["baseline_free_bytes"])
        if plan["baseline_free_bytes"] != baseline:
            raise ReportError("Baseline differs from selected volume snapshot")
    if "required_additional_bytes" in plan:
        _integer(plan["required_additional_bytes"])
        if plan["required_additional_bytes"] != expected:
            raise ReportError("Capacity shortfall is inconsistent with the goal snapshot")
    _validate_entries(plan["candidates"])
    _validate_entries(plan.get("directory_reviews", []), directory=True)
    for field in ("created_at", "scan_created_at"):
        if field in plan:
            _text(plan[field], 256, nullable=True)
    if "candidate_logical_bytes" in plan:
        _integer(plan["candidate_logical_bytes"])
        if plan["candidate_logical_bytes"] != sum(item["logical_bytes"] for item in plan["candidates"]):
            raise ReportError("Candidate logical-byte total is inconsistent")
    for field in ("excluded_system_files", "excluded_other_or_unknown_volume_files"):
        if field in plan:
            _integer(plan[field])
    if "automatic_reclaimable_bytes" in plan:
        _integer(plan["automatic_reclaimable_bytes"])
        if plan["automatic_reclaimable_bytes"] != 0:
            raise ReportError("A decision plan cannot claim automatic reclaimable bytes")
    if "goal_evaluation" in plan and plan["goal_evaluation"] != "unknown_until_user_choices_and_post_action_volume_measurement":
        raise ReportError("A decision plan cannot claim the goal was achieved")
    if "capacity_snapshot_status" in plan:
        expected_status = ("additional_space_requested" if plan["goal_kind"] == "additional_free_space" else
                           "below_free_target" if expected else "already_at_free_target_at_scan_time")
        if plan["capacity_snapshot_status"] != expected_status:
            raise ReportError("Capacity snapshot status is inconsistent")
    for text in _list(plan.get("limitations", []), 30):
        _text(text)
    return plan


def _managed_path(path):
    # Text-only extra conservatism if a supplied plan mislabels a managed path.
    parts = {part.casefold() for part in re.split(r"[\\/]", path)}
    return any(part.startswith("onedrive") for part in parts) or bool(parts & (scanner.PROTECTED_PARTS | scanner.SYSTEM_FILES | {
        "appdata", ".conda", ".npm", ".nuget", ".gradle", ".docker",
        "temp", "tmp", "cache", "caches", ".cache", "code cache", "cache_data",
        ".git", ".svn", "dropbox", "google drive", "googledrive", "icloud drive",
    }))


def _copy_scope_status(item, choice, goal_volume, application_assessments=None):
    if choice["action"] != "copy_then_release":
        return "not_copy_action"
    if application_assessments is not None and application_assessments[(False, item["path"])]["status"] == "registration_path_overlap":
        return "excluded_application_registration"
    if item["hardlink_count"] != 1:
        return "excluded_hardlinks"
    if item["category"] not in ORDINARY or _managed_path(item["path"]):
        return "excluded_managed_category"
    source = item.get("volume_id")
    if not source or not goal_volume:
        return "excluded_unknown_source"
    if source != goal_volume["volume_id"]:
        return "excluded_source_not_goal"
    destination = choice.get("destination_volume_id")
    if not destination:
        return "excluded_unknown_destination"
    if destination == source:
        return "excluded_same_volume"
    return "hypothetical_copy_scope"


def _analyze(plan, choices, application_assessments=None):
    if choices is None:
        return []
    _bounded_tree(choices)
    _object(choices, {"schema_version", "scenarios"}, {"schema_version", "scenarios"})
    if type(choices["schema_version"]) is not int or choices["schema_version"] != 1:
        raise ReportError("Expected choices schema_version 1")
    scenarios = _list(choices["scenarios"], 2)
    if not scenarios:
        raise ReportError("Provide one or two scenarios, or omit the choices input")
    files = {item["path"]: item for item in plan["candidates"]}
    names, summaries = set(), []
    for scenario in scenarios:
        _object(scenario, {"name", "choices"}, {"name", "choices"})
        name = scenario["name"]
        if name not in ("conservative", "expanded") or name in names:
            raise ReportError("Scenario names must be conservative/expanded and unique")
        names.add(name)
        rows, chosen = [], set()
        for choice in _list(scenario["choices"]):
            _object(choice, {"path", "action", "explanation", "consequence", "destination_volume_id"}, {"path", "action"})
            path = _path_data(choice["path"])
            if path not in files:
                raise ReportError("Choice path must exactly match a file candidate, not a directory or new path")
            key = scanner.path_key(path)
            if key in chosen:
                raise ReportError("Duplicate choice path")
            chosen.add(key)
            action = choice["action"]
            if action not in ("keep", "copy_then_release", "app_cleanup", "review"):
                raise ReportError("Unsupported proposed action")
            for field in ("explanation", "consequence"):
                if action != "review" or field in choice:
                    _text(choice.get(field))
            if "destination_volume_id" in choice:
                if action != "copy_then_release":
                    raise ReportError("Only copy_then_release accepts a destination declaration")
                _text(choice["destination_volume_id"], 256)
            item = files[path]
            status = _copy_scope_status(item, choice, plan.get("goal_volume"), application_assessments)
            rows.append({"path": path, "action": action, "explanation": choice.get("explanation"),
                         "consequence": choice.get("consequence"), "destination_volume_id": choice.get("destination_volume_id"),
                         "counted_logical_bytes": item["logical_bytes"] if status == "hypothetical_copy_scope" else 0,
                         "scope_status": status})
        summaries.append({
            "name": name, "rows": rows, "selected_logical_copy_scope_bytes": sum(row["counted_logical_bytes"] for row in rows),
            "proposed_file_count": len(rows), "unselected_file_count": len(files) - len(rows),
            "action_counts": {action: sum(row["action"] == action for row in rows) for action in ("keep", "copy_then_release", "app_cleanup", "review")},
            "destination_identity_verified": False, "authorization": False,
            "actual_reclaimed_bytes": None, "goal_achieved": None,
        })
    return summaries


def _application_assessments(plan, applications):
    if applications is None:
        return None
    _bounded_tree(applications)
    # make_assessor validates once and reuses a bounded text-only path index.
    assess = inventory_tools.make_assessor(applications)
    results = {}
    for directory, items in ((False, plan["candidates"]), (True, plan.get("directory_reviews", []))):
        for item in items:
            result = assess(item["path"], directory=directory)
            # Keep bounded per-target details. The full count still controls
            # reporting; source evidence remains in the supplied inventory.
            results[(directory, item["path"])] = {**result, "matches": result["matches"][:MAX_APPLICATION_MATCHES_SHOWN]}
    return results


def analyze_scenarios(plan, choices, applications=None):
    validate_plan(plan)
    return _analyze(plan, choices, _application_assessments(plan, applications))


def escape_text(value):
    """Escape untrusted strings as inert one-line Markdown table/prose text."""
    if value is None:
        return "—"
    text = str(value).replace("\r\n", " ⏎ ").replace("\r", " ⏎ ").replace("\n", " ⏎ ").replace("\t", " ⇥ ")
    hidden = {0x061C, 0x200B, 0x200E, 0x200F, 0x2028, 0x2029, 0xFEFF,
              *range(0x7F, 0xA0), *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
    text = "".join(f"[U+{ord(char):04X}]" if ord(char) in hidden or unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"}
                   else char for char in text)
    text = html.escape(text, quote=True)
    text = re.sub(r"([\\`*_{}\[\]()#+.!|~=-])", r"\\\1", text)
    # Entity-encode URI separators after escaping to prevent GFM bare-URL
    # autolinking, while the rendered path/prose remains human-readable.
    return text.replace(":", "&#58;").replace("/", "&#47;")


def _size(value, zh):
    if value is None:
        return "未知" if zh else "unknown"
    return f"{value:,} {'字节' if zh else 'bytes'} ({value / 1024**3:.3f} GiB)"


def _tradeoff(category, zh):
    if category == "possible_temp_or_cache":
        return ("目录名仅提示缓存；先确认归属。应用清理可能丢失离线重装资料，恢复可能需要重新下载或构建。" if zh else
                "A name only suggests cache content; establish ownership first. App cleanup can lose offline reinstall material; recovery may need downloads or rebuilding.")
    if category in ("application_data", "system_managed"):
        return ("先使用应用或 Windows 的存储/卸载功能核实；直接搬移可能影响配置或依赖，不能假定有自动恢复。" if zh else
                "Review through the owning app or Windows storage/uninstall controls. Direct relocation may break configuration or dependencies; automatic recovery is not assured.")
    return ("保留可继续原位置访问；另存要占用目标盘并验证副本。独立释放源文件后仅能从保留副本手动恢复；旧文件不等于无用。" if zh else
            "Keeping preserves access at the original location. A copy needs destination capacity and verification. Separately releasing a source requires manual recovery from the retained copy; age does not establish disposability.")


def _directory_tradeoff(category, zh):
    if category not in ORDINARY:
        return _tradeoff(category, zh)
    return ("汇总可能混合普通文件、应用数据和缓存。先查看内容、确认归属，再选择具体普通文件；尚未证明整个目录适合搬移或清理。" if zh else
            "An aggregate may mix ordinary files, app data and caches. Inspect contents and ownership before selecting specific ordinary files; suitability of the whole directory for relocation or cleanup is unproven.")


def _application_lines(applications, assessments, zh):
    pick = lambda chinese, english: chinese if zh else english
    lines = ["", pick("## 应用登记路径线索", "## Application registration path evidence"), "",
             pick("仅解释提供的卸载登记清单；没有读取注册表、应用目录或执行卸载命令。路径重叠不证明应用仍安装、文件所有权或可清理性；未关联不等于卸载残余。", "Only the supplied uninstall-registration inventory is interpreted. No registry, application directory or uninstall command is accessed or executed. Path overlap does not prove installed status, ownership or disposability; no match does not establish an orphan."), "",
             f"- {pick('登记清单采集时间（非安装或卸载时间）', 'Inventory collection time (not installation or removal time)')}: {escape_text(applications['created_at'])}",
             f"- {pick('证据范围', 'Evidence scope')}: {escape_text(applications['coverage'])}",
             f"- {pick('检查条目 / 保留登记 / 检查上限', 'Entries examined / retained registrations / examination limit')}: {applications['entries_examined']} / {len(applications['entries'])} / {applications['max_entries']}",
             f"- {pick('覆盖', 'Coverage')}: {pick('部分登记范围；存在未检查或失败项。', 'Partial registration coverage; some scopes or entries were not examined successfully.') if applications['incomplete'] else pick('所列登记范围未报告遗漏；便携软件、缺少登记和登记外目录仍未知。', 'No omissions reported within listed registration scopes; portable apps, absent registrations and other paths remain unknown.')}", "",
             pick("| 登记源 | 视图 | 范围状态 | 检查条目 | 记录错误数 |", "| Registry source | View | Scope status | Entries examined | Recorded errors |"),
             "|---|---|---|---:|---:|"]
    for scope in applications["scopes"]:
        lines.append(f"| {escape_text(scope['hive'])} | {escape_text(scope['view'])} | {escape_text(scope['status'])} | {scope['entries_examined']} | {len(scope['errors'])} |")
    lines += ["", pick("以下仅对计划已有文件和目录作词法路径关联，不查询路径实际身份；连接点、盘符映射和短名称别名未核验。父目录包含登记位置，不代表整个父目录归属该应用。", "The existing file and directory targets are compared lexically; actual path identities, junctions, drive mappings and short-name aliases are unverified. A directory containing a registered location is not wholly attributed to that application."), "",
              pick(f"每个目标最多显示 {MAX_APPLICATION_MATCHES_SHOWN} 条关联及其登记引用，总关联数另列；完整证据保留在输入 JSON。", f"At most {MAX_APPLICATION_MATCHES_SHOWN} matches and registration references are shown per target, with the full match count separately listed; the supplied JSON retains the complete evidence."), "",
              pick("| 目标 | 类型 | 关联结果 | 总关联数 | 显示的登记引用与关系 |", "| Target | Type | Assessment | Total matches | Shown registration references and relationships |"),
              "|---|---|---|---:|---|"]
    statuses = {
        "registration_path_overlap": ("登记路径重叠；先核实应用状态和归属", "registration path overlap; verify app status and ownership"),
        "no_registration_path_match": ("本清单未关联；归属未知", "no match in this inventory; ownership unknown"),
        "unsupported_candidate_path": ("路径形式不支持关联；归属未知", "candidate path unsupported for association; ownership unknown"),
    }
    relations = {
        "inside_registered_location": ("位于登记位置内", "inside registered location"),
        "contains_registered_location": ("目录包含登记位置", "directory contains registered location"),
    }
    references = {}
    for (directory, path), assessment in assessments.items():
        shown = []
        for match in assessment["matches"]:
            key = (match["hive"], match["view"], match["subkey"].lower())
            if key not in references:
                references[key] = (f"R{len(references) + 1}", match)
            shown.append(references[key][0] + " " + pick(*relations[match["relation"]]))
        omitted = assessment["match_count"] - len(assessment["matches"])
        if omitted:
            shown.append(pick(f"另有 {omitted} 条关联未展示", f"{omitted} additional matches not shown"))
        lines.append(f"| {escape_text(path)} | {pick('目录', 'directory') if directory else pick('文件', 'file')} | {pick(*statuses[assessment['status']])} | {assessment['match_count']} | {'; '.join(shown) or '—'} |")
    if not assessments:
        lines.append(pick("| 无计划目标 | — | 无关联判断 | 0 | — |", "| No plan targets | — | No assessment | 0 | — |"))
    if references:
        lines += ["", pick("仅列上表引用的登记信息；这些输入字段尚未独立核实。", "Only registrations referenced above are shown; their supplied fields are not independently verified."), "",
                  pick("| 引用 | 应用显示名 | 版本 | 发布者 | 登记安装位置 | 登记源 / 视图 / 子键 |", "| Reference | Display name | Version | Publisher | Registered install location | Registry source / view / subkey |"),
                  "|---|---|---|---|---|---|"]
        for reference, match in references.values():
            source = " / ".join((match["hive"], match["view"], match["subkey"]))
            lines.append(f"| {reference} | {escape_text(match['display_name'])} | {escape_text(match['display_version'])} | {escape_text(match['publisher'])} | {escape_text(match['install_location'])} | {escape_text(source)} |")
    lines += ["", pick("清理前核实应用当前状态、具体文件用途和共享依赖，再参考应用官方卸载或存储设置。登记路径重叠的文件不计入普通文件复制范围；任何副本计划仍不构成删除许可。", "Before cleanup, establish current app status, file purpose and shared dependencies, then consult official uninstall or storage settings. Files overlapping registered locations are excluded from ordinary-file copy scope; any copy proposal still grants no deletion permission."),
              pick("缺失安装位置、环境变量或不支持的路径形式不会按名称相似度补配，也不能用来证明没有关联。", "Missing install locations, environment variables and unsupported path forms are not replaced by name-based guesses and cannot establish the absence of an association."), ""]
    return lines


def render_report(plan, choices=None, language="zh", applications=None):
    if language not in ("zh", "en"):
        raise ReportError("language must be zh or en")
    validate_plan(plan)
    application_assessments = _application_assessments(plan, applications)
    scenarios = _analyze(plan, choices, application_assessments)
    zh = language == "zh"
    pick = lambda chinese, english: chinese if zh else english
    volume = plan.get("goal_volume")
    baseline = volume["free_bytes"] if volume else None
    required = plan["goal_bytes"] if plan["goal_kind"] == "additional_free_space" else max(plan["goal_bytes"] - baseline, 0)
    snapshot = (volume or {}).get("sampled_at") or plan.get("scan_created_at")
    volume_name = ((volume.get("path") or volume.get("queried_at") or "") + " [" + volume["volume_id"] + "]") if volume else None
    lines = [pick("# 磁盘空间决策报告", "# Disk space decision report"), "",
             pick("本报告只解释输入计划，不读取列出的文件，不执行复制、清理或删除，也不构成操作授权。", "This report interprets the supplied plan only. It does not read listed files, copy, clean or delete anything, or authorize operations."), "",
             pick("## 目标与容量快照", "## Goal and capacity snapshot"), "",
             f"- {pick('选定卷', 'Selected volume')}: {escape_text(volume_name)}",
             f"- {pick('快照时间', 'Snapshot time')}: {escape_text(snapshot)}",
             f"- {pick('目标', 'Goal')}: {pick('新增可用空间', 'Additional free space') if plan['goal_kind'] == 'additional_free_space' else pick('达到总可用空间', 'Total free-space target')} {_size(plan['goal_bytes'], zh)}",
             f"- {pick('快照可用空间', 'Free space at snapshot')}: {_size(baseline, zh)}",
             f"- {pick('按快照计算仍需新增', 'Additional space required by the snapshot')}: {_size(required, zh)}",
             f"- {pick('覆盖范围', 'Coverage')}: {pick('部分覆盖：存在未遍历或跳过内容。', 'Partial coverage: some content was skipped or not traversed.') if plan['scan_incomplete'] else pick('所选扫描范围内未报告已知遗漏；仍不是全盘、实时或内容依赖验证。', 'No known omissions reported within selected scan scope; this is not a whole-disk, live or dependency validation.')}", "",
             pick("容量只反映记录时刻；请重新测量后再决定。候选为空也不代表没有机会，其他卷可能占据了有界的最大文件样本。", "Capacity reflects the recorded instant; remeasure before deciding. An empty candidate list does not establish no opportunities: other volumes may dominate the bounded largest-file sample."), ""]
    if volume and volume.get("scan_roots"):
        lines += [pick("选定卷记录的扫描根目录：", "Recorded scan roots on the selected volume:"), ""]
        lines += ["- " + escape_text(root) for root in volume["scan_roots"]]
        lines.append("")
    if plan["goal_kind"] == "target_free_space" and required == 0:
        lines += [pick("记录时刻已达到可用空间目标。先重新测量，不据此建议继续删除。", "The recorded snapshot was already at the free-space target. Remeasure first; this is not a reason to delete more."), ""]
    lines += [pick("## 目录占用线索（不可相加）", "## Directory signals (not additive)"), "",
              pick("目录数值包含子目录，并与文件候选重叠。硬链接只归入首次观察路径，不能相加或当作可释放空间。", "Directory totals include descendants and overlap file candidates. Hard links are attributed to the first observed path; do not sum summaries or treat them as reclaimable space."), "",
              pick("| 目录 | 观察到的逻辑量 | 文件数 | 覆盖 | 取舍与恢复 |", "| Directory | Observed logical size | Files | Coverage | Tradeoffs and recovery |"),
              "|---|---:|---:|---|---|"]
    directories = plan.get("directory_reviews", [])
    for item in directories:
        coverage = pick("不完整", "incomplete") if item.get("incomplete", True) else pick("未报告遗漏", "no omissions reported")
        tradeoff = _directory_tradeoff(item["category"], zh)
        if application_assessments is not None and application_assessments[(True, item["path"])]["status"] == "registration_path_overlap":
            tradeoff = pick("与登记安装位置重叠；先拆分审查具体文件用途、归属及共享依赖。关联不代表整个目录归属该应用；核实官方支持的处理和恢复方式。", "Overlaps a registered install location. Review individual files, their purpose, ownership and shared dependencies separately. The whole directory is not attributed to the app; establish officially supported handling and recovery options.")
        lines.append(f"| {escape_text(item['path'])} | {_size(item['logical_bytes'], zh)} | {item['observed_files']} | {coverage} | {tradeoff} |")
    if not directories:
        lines.append(pick("| 无目录摘要 | — | — | 未知 | 可对明确目录重新扫描。 |", "| No directory summaries | — | — | unknown | A scoped rescan may help. |"))
    lines += ["", pick("## 文件候选（仅供审查）", "## File candidates (review only)"), "",
              pick("以下沿用计划顺序，不按年龄或名称自动判定可删；缓存提示不代表低风险。", "The input plan's order is retained. Age or naming does not determine disposability, and a cache hint does not establish low risk."), "",
              pick("| 文件 | 逻辑量 | 硬链接数 | 取舍与恢复 | 输入证据（未独立核验） |", "| File | Logical size | Hard links | Tradeoffs and recovery | Input evidence (not independently verified) |"),
              "|---|---:|---:|---|---|"]
    for item in plan["candidates"]:
        evidence = " / ".join(item.get("evidence", []))
        warning = pick(" 多重硬链接：删除此名称可能释放零字节。", " Multiple hard links: removing this name may release zero bytes.") if item["hardlink_count"] > 1 else ""
        tradeoff = _tradeoff(item["category"], zh)
        if application_assessments is not None and application_assessments[(False, item["path"])]["status"] == "registration_path_overlap":
            tradeoff = pick("与登记安装位置重叠；先核实应用当前状态、数据用途及共享依赖，查明官方卸载、存储或迁移方式及恢复要求。尚未证明适合按普通文件直接搬移或释放。", "Overlaps a registered install location. Verify current app status, data purpose and shared dependencies, then establish official uninstall, storage or migration options and recovery requirements. Direct ordinary-file relocation or release is unproven.")
        lines.append(f"| {escape_text(item['path'])} | {_size(item['logical_bytes'], zh)} | {item['hardlink_count']} | {tradeoff}{warning} | {escape_text(evidence or None)} |")
    if not plan["candidates"]:
        lines.append(pick("| 无文件候选 | — | — | 样本为空，不代表无清理机会。 | — |", "| No file candidates | — | — | An empty sample does not rule out opportunities. | — |"))
    if applications is not None:
        lines += _application_lines(applications, application_assessments, zh)
    lines += ["", pick("## 可选方案推演", "## Optional what-if scenarios"), "",
              pick("方案是提议，不是授权或执行请求；未选择的文件没有拟议操作，不能推断为同意或已决定保留。", "Scenarios are proposals, not authorization or execution requests. Unselected files have no proposed action; neither consent nor an explicit keep decision is inferred."), "",
              pick("目标卷身份来自输入计划；目标存放卷仅由用户声明、尚未核验。汇总只表示去重后的拟议逻辑文件范围，不是物理释放估计，也不能证明填补缺口或达成目标。复制本身不会释放源盘空间。", "The goal-volume identity comes from the input plan; destination identities are user-declared and unverified. Totals describe deduplicated proposed logical file scope, not estimated physical reclaim, shortfall coverage or goal achievement. Copying alone releases no source space."), ""]
    status_labels = {
        "hypothetical_copy_scope": ("仅计入假设逻辑范围；目标卷未核验", "hypothetical logical scope only; destination unverified"),
        "excluded_hardlinks": ("多重硬链接，不计入", "hard links; not counted"),
        "excluded_managed_category": ("系统/应用/缓存内容，不计入普通迁移", "managed/app/cache content; not counted as ordinary migration"),
        "excluded_application_registration": ("与应用登记位置重叠，不计入普通文件复制范围", "overlaps an application registration; not counted as ordinary-file copy scope"),
        "excluded_unknown_source": ("源卷或目标卷范围未知，不计入", "source or goal volume unknown; not counted"),
        "excluded_source_not_goal": ("源卷不属于空间目标，不计入", "source is not the goal volume; not counted"),
        "excluded_unknown_destination": ("未声明目标存放卷，不计入", "destination undeclared; not counted"),
        "excluded_same_volume": ("声明为同卷，不计入", "declared same volume; not counted"),
        "not_copy_action": ("非跨盘普通文件复制提议，不计入", "not an ordinary cross-volume copy proposal; not counted"),
    }
    actions = {"keep": ("保留提议", "propose keep"), "copy_then_release": ("先复制校验，再独立评审源文件释放", "copy/verify, then separately review source release"),
               "app_cleanup": ("应用清理提议（需核实归属与影响）", "propose app cleanup (verify ownership and impact)"), "review": ("继续审查", "review further")}
    if not scenarios:
        lines += [pick("未提供方案选择；所有候选均无拟议操作。", "No choices were supplied; every candidate has no proposed action."), ""]
    else:
        lines += [pick("| 方案 | 保留提议 | 复制后独立评审释放 | 应用清理提议 | 继续审查 | 无拟议操作 | 假设逻辑复制范围（非物理释放） |", "| Scenario | Keep proposals | Copy then separately review release | App-cleanup proposals | Further review | No proposed action | Hypothetical logical copy scope (not physical reclaim) |"),
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for scenario in scenarios:
            count = scenario["action_counts"]
            name = pick("保守" if scenario["name"] == "conservative" else "扩展", scenario["name"].capitalize())
            lines.append(f"| {name} | {count['keep']} | {count['copy_then_release']} | {count['app_cleanup']} | {count['review']} | {scenario['unselected_file_count']} | {_size(scenario['selected_logical_copy_scope_bytes'], zh)} |")
        lines.append("")
    for scenario in scenarios:
        lines += ["### " + pick("保守方案" if scenario["name"] == "conservative" else "扩展方案", scenario["name"].capitalize()), "",
                  pick("名称仅区分提议，不证明任何操作低风险。", "The name distinguishes proposals; it does not establish low risk."), "",
                  f"- {pick('假设选中的逻辑复制范围', 'Hypothetical selected logical copy scope')}: {_size(scenario['selected_logical_copy_scope_bytes'], zh)}",
                  f"- {pick('未选择文件数（无拟议操作）', 'Unselected files (no proposed action)')}: {scenario['unselected_file_count']}", "",
                  pick("| 文件 | 拟议动作 | 原因 | 后果 | 目标存放卷（未核验） | 汇总说明 |", "| File | Proposed action | Explanation | Consequence | Destination (unverified) | Scope accounting |"),
                  "|---|---|---|---|---|---|"]
        for row in scenario["rows"]:
            lines.append(f"| {escape_text(row['path'])} | {pick(*actions[row['action']])} | {escape_text(row['explanation'])} | {escape_text(row['consequence'])} | {escape_text(row['destination_volume_id'])} | {pick(*status_labels[row['scope_status']])} |")
        lines.append("")
    lines += [pick("## 决策前还需核实", "## What remains to establish"), "",
              pick("- 确认文件用途、保留价值、应用归属和可恢复副本；时间戳不能证明卸载残余。", "- Establish purpose, value, application ownership and recoverable copies; timestamps do not prove uninstall remnants."),
              pick("- 核实实际目标卷和可用容量，完成复制校验；源文件释放需要单独计划与已有授权核对。", "- Verify the real destination volume and capacity, then verify any copy. Source release needs its own plan and authorization check."),
              pick("- 应用清理可能丢失缓存和离线重装能力；恢复依赖重新下载或构建，不能假定能撤销。", "- App cleanup can lose cache and offline reinstall capability. Recovery may depend on downloads or rebuilding; do not assume undo."),
              pick("- 实际处理后重新测量卷空间；逻辑字节、压缩/稀疏文件、硬链接和并发写入会影响物理变化。", "- Remeasure volume space after actual work; compression, sparse files, hard links and concurrent activity affect physical changes."), ""]
    return "\n".join(lines)


def _report_path(value):
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        raise ReportError("An explicit local report path is required")
    if os.name == "nt" and (raw.startswith(("\\\\", "//")) or re.match(r"^[a-zA-Z]:(?:$|[^\\/])", raw)):
        raise ReportError("UNC, device and drive-relative report paths are unsupported")
    name = Path(raw).name
    if not name or name.endswith((".", " ")) or scanner.RESERVED_NAME.match(name) or any(ord(char) < 32 or char in '<>:"|?*' for char in name):
        raise ReportError("Report filename must be portable; device names and alternate streams are unsupported")
    return scanner.absolute_path(raw)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReportError("Duplicate JSON key")
        result[key] = value
    return result


def load_json(path, max_bytes=MAX_INPUT_BYTES):
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_INPUT_BYTES:
        raise ReportError("Invalid JSON byte limit")
    source = _report_path(path)
    scanner.check_ancestors(source)
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
        raise ReportError("JSON input must be a bounded ordinary file")
    with source.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ReportError("JSON input exceeds its byte limit")
    try:
        result = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                            parse_constant=lambda value: (_ for _ in ()).throw(ReportError("Nonfinite JSON number")))
        _bounded_tree(result)
    except (UnicodeError, RecursionError) as error:
        raise ReportError("Invalid UTF-8 or excessively nested JSON") from error
    return result


def write_report(path, text):
    if not isinstance(text, str) or len(text) > 8 * MAX_INPUT_BYTES:
        raise ReportError("Invalid or oversized Markdown report")
    output = _report_path(path)
    scanner.check_ancestors(output.parent)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="Existing disk_scan plan JSON")
    parser.add_argument("--choices", help="Optional hypothetical choices JSON; never authorization")
    parser.add_argument("--applications", help="Optional existing application-inventory JSON; read supplied evidence only")
    parser.add_argument("--language", choices=("zh", "en"), default="zh")
    parser.add_argument("--output", required=True, help="New UTF-8 Markdown file; never overwrite")
    args = parser.parse_args(argv)
    try:
        plan = load_json(args.plan)
        choices = load_json(args.choices) if args.choices else None
        applications = load_json(args.applications) if args.applications else None
        text = render_report(plan, choices, args.language, applications)
        write_report(args.output, text)
        print(json.dumps({"report_created": True, "language": args.language, "operations_executed": False}))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(f"disk-steward decision report: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
