"""Core pipeline: collect, enrich, score, and export XHS KOC candidates.

V1: Claude owns semantics via persona_spec + query_packs YAML.
    Script owns execution: search notes, normalize, rank creators, score, export.
V0: Legacy persona/keyword_pool YAML, backward-compatible.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:
    yaml = None


# ---------------------------------------------------------------------------
# Limits per scale
# ---------------------------------------------------------------------------

V0_LIMITS: dict[str, Any] = {
    "max_queries": 8,
    "notes_per_query": 10,
    "max_notes": 30,
    "max_creators": 15,
    "comment_notes": 15,
    "comments_per_note": 20,
    "sleep_between_calls": 3,
    "sleep_between_queries": 10,
}

V1_LIMITS: dict[str, Any] = {
    "max_packs": 5,
    "max_queries_per_pack": 6,
    "notes_per_query": 8,
    "max_notes": 60,
    "max_creators": 25,
    "comment_notes": 20,
    "comments_per_note": 20,
    "sleep_between_calls": 3,
    "sleep_between_pack": 15,
}

V1_LIMITS_LARGE: dict[str, Any] = {
    "max_packs": 10,
    "max_queries_per_pack": 8,
    "notes_per_query": 10,
    "max_notes": 200,
    "max_creators": 100,
    "comment_notes": 30,
    "comments_per_note": 20,
    "sleep_between_calls": 4,
    "sleep_between_pack": 20,
}

V1_LIMITS_XLARGE: dict[str, Any] = {
    "max_packs": 15,
    "max_queries_per_pack": 8,
    "notes_per_query": 12,
    "max_notes": 600,
    "max_creators": 300,
    "comment_notes": 40,
    "comments_per_note": 20,
    "sleep_between_calls": 6,
    "sleep_between_pack": 30,
}

SCALE_LIMITS = {
    "normal": V1_LIMITS,
    "large": V1_LIMITS_LARGE,
    "xlarge": V1_LIMITS_XLARGE,
}

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------

BASE_CSV_FIELDS = [
    "creator_name", "xhs_user_id", "profile_url", "follower_count", "bio",
    "matched_persona", "score", "priority", "content_tags", "audience_signals",
    "sample_notes", "avg_likes", "avg_comments", "match_reason", "risk_reason",
    "next_action", "status",
]

V1_CSV_FIELDS = BASE_CSV_FIELDS + [
    "follower_tier", "discovery_queries", "discovery_packs", "high_signal_notes",
    "retrieval_reason", "specificity_signals",
]

# Follower tier boundaries (exact when follower_count known; estimated from avg_likes otherwise)
_TIER_LABELS_EXACT = [(1000, "<1K"), (5000, "1K-5K"), (10000, "5K-10K"), (50000, "10K-50K"), (float("inf"), ">50K")]
_TIER_LABELS_EST   = [(1000, "~<1K"), (5000, "~1K-5K"), (10000, "~5K-10K"), (50000, "~10K-50K"), (float("inf"), "~>50K")]
# avg_likes → estimated follower bucket upper bound (rough XHS engagement heuristic ~5-10% rate)
_LIKES_TO_FOLLOWERS = [(30, 1000), (200, 5000), (800, 10000), (3000, 50000), (float("inf"), 200000)]


def compute_follower_tier(follower_count: int | str, avg_likes: int) -> str:
    fc = coerce_int(follower_count, default=0)
    if fc > 0:
        for threshold, label in _TIER_LABELS_EXACT:
            if fc < threshold:
                return label
        return ">50K"
    # Estimate from avg_likes
    est_followers = 0
    for likes_threshold, est_fc in _LIKES_TO_FOLLOWERS:
        if avg_likes <= likes_threshold:
            est_followers = est_fc
            break
    for threshold, label in _TIER_LABELS_EST:
        if est_followers < threshold:
            return label
    return "~>50K"

# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

LEXICONS = {
    "identity_terms": ["留学生", "留子", "海归", "湾区", "英国留学", "美国留学", "海外生活", "伦敦", "纽约", "硅谷"],
    "content_terms": ["生活向", "日常", "vlog", "租房", "实习", "找工作", "毕业", "独立生活", "搬家", "做饭", "周末"],
    "circle_terms": ["founder", "startup", "创业", "AI", "app", "SaaS", "独立开发", "tech", "VC", "投资人", "融资", "build in public"],
    "scene_terms": ["我的 app", "iMessage", "创业日常", "build in public", "湾区生活", "side project", "实习日常"],
    "exclude_terms": ["中介", "课程", "低价申请", "机构", "广告", "抽奖", "互粉", "顾问", "报名", "加微信", "私信链接"],
}

REALNESS_TERMS = ["我", "我的", "自己", "今天", "日常", "记录", "生活", "搬家", "租房", "实习", "毕业", "找工作", "做饭", "周末", "复盘", "踩坑"]
SPAM_TERMS = ["互粉", "抽奖", "求链接", "蹲", "dd", "已私", "机器人"]
HARD_AD_TERMS = ["广告", "合作", "课程", "私信链接", "低价", "机构", "中介", "顾问", "报名", "领取资料", "加微信", "🔗"]
DEFAULT_CIRCLE_TERMS = LEXICONS["circle_terms"] + ["产品", "开发者", "创业者", "投资", "seed round", "天使轮"]
SPECIFICITY_REGEXES = [
    (r"\bGRE\s*\d{3}\b", re.IGNORECASE),
    (r"\bGPA\s*\d(?:\.\d+)?\b", re.IGNORECASE),
    (r"\b[A-Z]{2,8}\b", 0),
    (r"\d{2,4}\s*(?:分|k|K|万|offer)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Note:
    note_id: str = ""
    note_url: str = ""
    xsec_token: str = ""
    title: str = ""
    content: str = ""
    creator_id: str = ""
    creator_name: str = ""
    liked_count: int = 0
    comment_count: int = 0
    collect_count: int = 0
    tags: list[str] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    matched_keywords: set[str] = field(default_factory=set)
    initial_score: float = 0.0
    query: str = ""
    query_pack: str = ""
    matched_signal_keywords: list[str] = field(default_factory=list)
    matched_specificity_markers: list[str] = field(default_factory=list)


@dataclass
class Creator:
    key: str
    creator_name: str = ""
    xhs_user_id: str = ""
    profile_url: str = ""
    bio: str = ""
    follower_count: int | str = ""
    notes: list[Note] = field(default_factory=list)
    recent_notes: list[dict[str, Any]] = field(default_factory=list)
    user_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunConfig:
    mode: str
    persona_text: str
    raw_spec: dict[str, Any]
    query_packs: OrderedDict[str, dict[str, Any]]
    signal_keywords: list[str]
    ordinary_terms: list[str]
    anti_signals: list[str]
    target_circles: list[str]
    pool: dict[str, list[str]] = field(default_factory=dict)
    scale: str = "normal"
    seed_creators: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100000000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return default


def unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload and ("ok" in payload or "schema_version" in payload):
        return payload.get("data") or {}
    return payload or {}


def load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    if yaml is None:
        raise RuntimeError("PyYAML is required for YAML files. Install with: pip install pyyaml")
    data = yaml.safe_load(text)
    return data or {}


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    if yaml is None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def unique_keep_order(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(text_values(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(text_values(item))
        return out
    return [str(value)]


def extract_terms_from_texts(texts: list[str]) -> list[str]:
    stop = {"方向", "内容", "真实", "真实感", "非机构", "个人", "有", "和", "或", "的", "人", "博主"}
    terms: list[str] = []
    for text in texts:
        terms.append(text)
        parts = re.split(r"[\s,，、/|;；:：()（）\[\]【】]+", text)
        for part in parts:
            part = part.strip()
            if len(part) >= 2 and part not in stop:
                terms.append(part)
    return unique_keep_order(terms)


def make_slug(text: str, max_len: int = 20) -> str:
    """Convert persona identity text into a filesystem-safe slug."""
    slug = re.sub(r"[^\w一-鿿]", "", text)
    return slug[:max_len] if slug else "run"


def make_run_dir(output_base: Path, config: RunConfig, run_id: str) -> Path:
    identity = text_values(
        (config.raw_spec.get("persona_spec") or {}).get("creator_profile", {}).get("identity") or config.persona_text
    )
    slug = make_slug(identity[0] if identity else config.persona_text)
    run_dir = output_base / "runs" / f"{run_id}_{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    latest = output_base / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(run_dir.resolve())
    except Exception:
        (output_base / "latest.txt").write_text(str(run_dir), encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def detect_keyword_pool(persona_text: str, explicit_pool: dict[str, Any] | None = None) -> dict[str, list[str]]:
    text_lower = persona_text.lower()
    pool: dict[str, list[str]] = {key: [] for key in LEXICONS}
    explicit_pool = explicit_pool or {}
    for key in pool:
        values = explicit_pool.get(key) or explicit_pool.get(key.replace("_terms", "")) or []
        if isinstance(values, str):
            values = [values]
        pool[key].extend(values)
    for key, terms in LEXICONS.items():
        pool[key].extend([term for term in terms if term.lower() in text_lower])
    if any(term in text_lower for term in ["留子", "留学", "海外", "湾区", "海归"]):
        pool["identity_terms"].extend(["留子", "留学生", "海外生活", "湾区"])
    if any(term in text_lower for term in ["生活", "真实", "日常", "vlog"]):
        pool["content_terms"].extend(["生活向", "日常", "vlog", "独立生活"])
    if any(term.lower() in text_lower for term in ["founder", "投资人", "tech", "ai", "app", "vc", "创业"]):
        pool["circle_terms"].extend(["founder", "投资人", "tech", "AI", "app", "VC", "创业"])
        pool["scene_terms"].extend(["我的 app", "创业日常", "build in public"])
    pool["exclude_terms"].extend(["中介", "课程", "低价申请", "机构", "广告", "抽奖", "互粉"])
    return {key: unique_keep_order(values) for key, values in pool.items()}


def build_v0_queries(pool: dict[str, list[str]], max_queries: int) -> OrderedDict[str, dict[str, Any]]:
    ids = pool.get("identity_terms", [])
    contents = pool.get("content_terms", [])
    circles = pool.get("circle_terms", [])
    scenes = pool.get("scene_terms", [])
    raw: list[str] = []
    if ids and contents:
        raw.extend([f"{ids[0]} {term}" for term in contents[:3]])
    if ids and circles:
        raw.extend([f"{ids[0]} {term}" for term in circles[:3]])
    if contents and circles:
        raw.extend([f"{contents[0]} {term}" for term in circles[:2]])
    raw.extend(scenes[:3])
    if ids and scenes:
        raw.extend([f"{ids[0]} {scene}" for scene in scenes[:2]])
    raw.extend(["留子 日常", "留学生 生活", "湾区生活", "创业日常", "tech 日常"])
    return OrderedDict([("v0_keywords", {"purpose": "V0 direct keyword search", "queries": unique_keep_order(raw)[:max_queries]})])


def load_run_config(persona_yaml: Path | None, persona_text: str | None, scale: str = "normal") -> RunConfig:
    limits = SCALE_LIMITS.get(scale, V1_LIMITS)
    if persona_yaml:
        data = load_yaml_or_json(persona_yaml)
        if "persona_spec" in data:
            return load_v1_config(data, limits, scale)
        return load_v0_config(data, persona_text, scale)
    if not persona_text:
        raise SystemExit("Provide --persona-text or --persona-yaml.")
    pool = detect_keyword_pool(persona_text)
    return RunConfig(
        mode="v0", persona_text=persona_text, raw_spec={"persona": {"description": persona_text}, "keyword_pool": pool},
        query_packs=build_v0_queries(pool, V0_LIMITS["max_queries"]),
        signal_keywords=unique_keep_order(pool["circle_terms"] + pool["scene_terms"]),
        ordinary_terms=unique_keep_order(pool["identity_terms"] + pool["content_terms"]),
        anti_signals=pool["exclude_terms"], target_circles=pool["circle_terms"], pool=pool, scale=scale,
    )


def load_v0_config(data: dict[str, Any], persona_text_override: str | None, scale: str) -> RunConfig:
    persona = data.get("persona", data)
    text_parts = []
    for key in ["description", "name"]:
        if persona.get(key):
            text_parts.append(str(persona[key]))
    for key in ["must_have", "nice_to_have", "avoid"]:
        text_parts.extend(text_values(persona.get(key)))
    persona_text = persona_text_override or " ".join(text_parts)
    pool = detect_keyword_pool(persona_text, data.get("keyword_pool") or {})
    return RunConfig(
        mode="v0", persona_text=persona_text, raw_spec=data,
        query_packs=build_v0_queries(pool, V0_LIMITS["max_queries"]),
        signal_keywords=unique_keep_order(pool["circle_terms"] + pool["scene_terms"]),
        ordinary_terms=unique_keep_order(pool["identity_terms"] + pool["content_terms"]),
        anti_signals=pool["exclude_terms"], target_circles=pool["circle_terms"], pool=pool, scale=scale,
    )


def load_v1_config(data: dict[str, Any], limits: dict[str, Any], scale: str) -> RunConfig:
    spec = data.get("persona_spec") or {}
    creator_profile = spec.get("creator_profile") or {}
    audience_proxy = spec.get("audience_proxy") or {}
    content_evidence = spec.get("content_evidence") or {}
    query_packs_raw = data.get("query_packs") or {}
    query_packs: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for pack_name, pack in list(query_packs_raw.items())[: limits["max_packs"]]:
        queries = unique_keep_order(text_values((pack or {}).get("queries")))[: limits["max_queries_per_pack"]]
        query_packs[str(pack_name)] = {"purpose": str((pack or {}).get("purpose") or ""), "queries": queries}
    ordinary_terms = extract_terms_from_texts(
        text_values(creator_profile.get("identity")) + text_values(creator_profile.get("content_style"))
        + text_values(creator_profile.get("must_have")) + text_values(creator_profile.get("nice_to_have"))
    )
    signal_keywords = unique_keep_order(text_values(content_evidence.get("signal_keywords")))
    target_circles = unique_keep_order(text_values(audience_proxy.get("target_circles")))
    anti_signals = unique_keep_order(text_values(spec.get("anti_signals")) or LEXICONS["exclude_terms"])
    persona_text = "；".join(
        text_values(creator_profile.get("identity")) + text_values(creator_profile.get("content_style"))
        + text_values(creator_profile.get("must_have")) + text_values(creator_profile.get("nice_to_have"))
        + target_circles
    )
    seed_creators = unique_keep_order(text_values(spec.get("seed_creators")))
    return RunConfig(
        mode="v1", persona_text=persona_text, raw_spec=data, query_packs=query_packs,
        signal_keywords=signal_keywords, ordinary_terms=ordinary_terms,
        anti_signals=anti_signals, target_circles=target_circles,
        pool={"identity_terms": ordinary_terms, "content_terms": [], "circle_terms": target_circles,
              "scene_terms": signal_keywords, "exclude_terms": anti_signals},
        scale=scale, seed_creators=seed_creators,
    )


# ---------------------------------------------------------------------------
# XHS runner (subprocess wrapper)
# ---------------------------------------------------------------------------

class ProfileUnavailable(RuntimeError):
    pass


class XhsRunner:
    def __init__(self, offline_fixture: dict[str, Any] | None, sleep_calls: bool, limits: dict[str, Any]):
        self.offline = offline_fixture
        self.sleep_calls = sleep_calls
        self.limits = limits
        self.search_index = 0

    def check_live_ready(self) -> None:
        if self.offline is not None:
            return
        if shutil.which("xhs") is None:
            raise SystemExit(
                "xiaohongshu-cli is not installed.\n"
                "Install with: uv tool install xiaohongshu-cli\n"
                "Or:          pip install xiaohongshu-cli"
            )
        payload = self._run(["status", "--json"], sleep_after=False)
        data = unwrap(payload)
        if isinstance(payload, dict) and payload.get("ok") is False:
            code = (payload.get("error") or {}).get("code", "unknown")
            raise SystemExit(f"xhs auth is not ready ({code}). Run: xhs login  or  xhs login --qrcode")
        if isinstance(data, dict) and data.get("authenticated") is False:
            raise SystemExit("xhs auth is not ready. Run: xhs login  or  xhs login --qrcode")
        user = data.get("user") if isinstance(data, dict) else {}
        if isinstance(user, dict) and user.get("guest") is True:
            raise SystemExit("xhs is authenticated as a guest. Run: xhs login  or  xhs login --qrcode")

    def get_authed_user(self) -> str:
        if self.offline is not None:
            return "offline"
        try:
            payload = self._run(["status", "--json"], sleep_after=False)
            data = unwrap(payload)
            user = data.get("user") if isinstance(data, dict) else {}
            return (user or {}).get("nickname") or (user or {}).get("username") or "unknown"
        except Exception:
            return "unknown"

    def search(self, keyword: str) -> dict[str, Any]:
        if self.offline is not None:
            entries = self.offline.get("search", [])
            if not isinstance(entries, list):
                return unwrap(entries)
            for entry in entries:
                if entry.get("keyword") == keyword:
                    return unwrap(entry.get("payload"))
            if all(isinstance(e, dict) and "keyword" in e for e in entries):
                return {"items": []}
            if self.search_index < len(entries):
                payload = unwrap(entries[self.search_index].get("payload"))
                self.search_index += 1
                return payload
            return {"items": []}
        return unwrap(self._run(["search", keyword, "--json"]))

    def read(self, note: Note) -> dict[str, Any]:
        if self.offline is not None:
            return unwrap((self.offline.get("read") or {}).get(note.note_id, {}))
        # xhs read does not support --json; output is YAML
        args = ["read", note.note_id]
        if note.xsec_token:
            args.extend(["--xsec-token", note.xsec_token])
        return unwrap(self._run_yaml(args))

    def comments(self, note: Note) -> dict[str, Any]:
        if self.offline is not None:
            return unwrap((self.offline.get("comments") or {}).get(note.note_id, {}))
        args = ["comments", note.note_id, "--json"]
        if note.xsec_token:
            args.extend(["--xsec-token", note.xsec_token])
        return unwrap(self._run(args))

    def user(self, user_id: str) -> dict[str, Any]:
        if self.offline is not None:
            payload = (self.offline.get("user") or {}).get(user_id, {})
            if isinstance(payload, dict) and payload.get("ok") is False:
                raise ProfileUnavailable(f"offline profile unavailable for {user_id}")
            return unwrap(payload)
        try:
            return unwrap(self._run(["user", user_id, "--json"]))
        except RuntimeError as exc:
            if "code\": -1" in str(exc) or '"code": -1' in str(exc):
                raise ProfileUnavailable(str(exc)) from exc
            raise

    def user_posts(self, user_id: str) -> dict[str, Any]:
        if self.offline is not None:
            payload = (self.offline.get("user_posts") or {}).get(user_id, {})
            if isinstance(payload, dict) and payload.get("ok") is False:
                raise ProfileUnavailable(f"offline user-posts unavailable for {user_id}")
            return unwrap(payload)
        try:
            return unwrap(self._run(["user-posts", user_id, "--json"]))
        except RuntimeError as exc:
            if "code\": -1" in str(exc) or '"code": -1' in str(exc):
                raise ProfileUnavailable(str(exc)) from exc
            raise

    def _run(self, args: list[str], sleep_after: bool = True) -> Any:
        cmd = ["xhs", *args]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if sleep_after and self.sleep_calls:
            time.sleep(self.limits["sleep_between_calls"])
        output = proc.stdout.strip() or proc.stderr.strip()
        try:
            payload = json.loads(output) if output else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse JSON from {' '.join(cmd)}: {output[:500]}") from exc
        if proc.returncode != 0:
            error = payload.get("error") if isinstance(payload, dict) else None
            message = (error or {}).get("message") or output
            raise RuntimeError(f"xhs command failed: {' '.join(cmd)}: {message}")
        return payload

    def _run_yaml(self, args: list[str], sleep_after: bool = True) -> Any:
        """Run an xhs command whose output is YAML (e.g. xhs read)."""
        cmd = ["xhs", *args]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if sleep_after and self.sleep_calls:
            time.sleep(self.limits["sleep_between_calls"])
        output = proc.stdout.strip() or proc.stderr.strip()
        if not output:
            return {}
        if yaml is not None:
            try:
                return yaml.safe_load(output) or {}
            except Exception:
                pass
        # fallback: try JSON (in case CLI upgrades to JSON output)
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {}


# ---------------------------------------------------------------------------
# Note normalization
# ---------------------------------------------------------------------------

def extract_tags(note_card: dict[str, Any]) -> list[str]:
    tags = []
    for item in note_card.get("tag_list") or note_card.get("tags") or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("tag_name")
        else:
            name = str(item)
        if name:
            tags.append(str(name))
    return unique_keep_order(tags)


def normalize_note_item(item: dict[str, Any]) -> Note:
    note_card = item.get("note_card", item) if isinstance(item, dict) else {}
    if item.get("model_type") and item.get("model_type") != "note":
        return Note()
    user = note_card.get("user") or item.get("user") or {}
    interact = note_card.get("interact_info") or item.get("interact_info") or {}
    note_id = str(item.get("id") or note_card.get("note_id") or note_card.get("id") or "")
    token = str(item.get("xsec_token") or note_card.get("xsec_token") or "")
    note_url = str(item.get("url") or note_card.get("url") or "")
    if not note_url and note_id:
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
        if token:
            note_url += f"?xsec_token={token}"
    return Note(
        note_id=note_id, note_url=note_url, xsec_token=token,
        title=str(note_card.get("title") or note_card.get("display_title") or item.get("title") or ""),
        content=str(note_card.get("desc") or note_card.get("content") or item.get("desc") or ""),
        creator_id=str(user.get("user_id") or user.get("id") or user.get("userid") or ""),
        creator_name=str(user.get("nickname") or user.get("nick_name") or user.get("name") or ""),
        liked_count=coerce_int(interact.get("liked_count") or item.get("liked_count")),
        comment_count=coerce_int(interact.get("comment_count") or item.get("comment_count")),
        collect_count=coerce_int(interact.get("collected_count") or interact.get("collect_count") or item.get("collect_count")),
        tags=extract_tags(note_card),
    )


def merge_note_detail(note: Note, data: dict[str, Any]) -> Note:
    items = data.get("items") if isinstance(data, dict) else None
    if items and isinstance(items, list):
        detail = normalize_note_item(items[0])
    elif isinstance(data, dict) and (data.get("note_card") or data.get("title")):
        detail = normalize_note_item(data)
    else:
        return note
    for attr in ["title", "content", "creator_id", "creator_name", "note_url", "xsec_token"]:
        value = getattr(detail, attr)
        if value:
            setattr(note, attr, value)
    for attr in ["liked_count", "comment_count", "collect_count"]:
        value = getattr(detail, attr)
        if value:
            setattr(note, attr, value)
    note.tags = unique_keep_order(note.tags + detail.tags)
    return note


def normalize_comments(data: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    comments = data.get("comments") if isinstance(data, dict) else []
    out = []
    for comment in (comments or [])[:limit]:
        user = comment.get("user_info") or comment.get("user") or {}
        out.append({
            "nickname": str(user.get("nickname") or user.get("name") or ""),
            "content": str(comment.get("content") or comment.get("text") or ""),
            "like_count": coerce_int(comment.get("like_count")),
        })
    return out


def normalize_user(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    basic = data.get("basic_info") or data
    interactions = data.get("interactions") or []
    stats: dict[str, Any] = {}
    if isinstance(interactions, list):
        for item in interactions:
            stats[str(item.get("type") or item.get("name") or "").lower()] = item.get("count")
    follower = basic.get("fans") or basic.get("fans_count") or basic.get("follower_count") or stats.get("fans") or stats.get("followers")
    user_id = str(basic.get("user_id") or data.get("user_id") or basic.get("id") or "")
    profile_url = str(basic.get("profile_url") or data.get("profile_url") or "")
    if not profile_url and user_id:
        profile_url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
    return {
        "user_id": user_id,
        "nickname": str(basic.get("nickname") or basic.get("nick_name") or data.get("nickname") or ""),
        "bio": str(basic.get("desc") or basic.get("bio") or data.get("desc") or ""),
        "follower_count": coerce_int(follower, default=0) if follower not in (None, "") else "",
        "profile_url": profile_url,
    }


def normalize_user_posts(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        notes = data
    elif isinstance(data, dict):
        notes = data.get("notes") or data.get("note_list") or data.get("items") or []
    else:
        notes = []
    out = []
    for item in notes[:10]:
        interact = item.get("interact_info") or {}
        out.append({
            "note_id": str(item.get("note_id") or item.get("id") or ""),
            "title": str(item.get("display_title") or item.get("title") or ""),
            "content": str(item.get("desc") or item.get("content") or ""),
            "liked_count": coerce_int(item.get("liked_count") or interact.get("liked_count")),
            "comment_count": coerce_int(item.get("comment_count") or interact.get("comment_count")),
        })
    return out


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------

def text_blob_for_note(note: Note) -> str:
    return " ".join([note.title, note.content, " ".join(note.tags)])


def count_terms(text: str, terms: list[str]) -> Counter:
    lower = text.lower()
    counts: Counter = Counter()
    for term in terms:
        if not term:
            continue
        count = lower.count(term.lower())
        if count:
            counts[term] += count
    return counts


def unique_hits(text: str, terms: list[str]) -> list[str]:
    lower = text.lower()
    return unique_keep_order([term for term in terms if term and term.lower() in lower])


def detect_specificity_values(text: str, signal_keywords: list[str]) -> list[str]:
    values: list[str] = []
    for pattern, flags in SPECIFICITY_REGEXES:
        values.extend(re.findall(pattern, text, flags=flags))
    lower = text.lower()
    specificity_signals = {"gre", "cmu", "ucla", "berkeley", "stanford", "mit", "acl", "iclr", "neurips", "nlp", "cs", "phd", "gpa"}
    for keyword in signal_keywords:
        if keyword.lower() in lower and (keyword.lower() in specificity_signals or re.search(r"[A-Z]{2,}", keyword)):
            values.append(keyword)
    return unique_keep_order(values)


def annotate_note(note: Note, config: RunConfig) -> None:
    blob = text_blob_for_note(note)
    note.matched_signal_keywords = unique_hits(blob, config.signal_keywords)
    note.matched_specificity_markers = detect_specificity_values(blob, config.signal_keywords)
    note.matched_keywords.update(note.matched_signal_keywords)
    note.matched_keywords.update(unique_hits(blob, config.ordinary_terms))
    note.initial_score = high_signal_score_for_note(note)


def high_signal_score_for_note(note: Note) -> float:
    return (
        len(note.matched_signal_keywords) * 4
        + len(note.matched_specificity_markers) * 6
        + min(note.liked_count, 1000) / 100
        + min(note.comment_count, 100) / 20
    )


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def rescue_seeds(runner: XhsRunner, config: RunConfig, notes_by_id: dict[str, Note]) -> int:
    """Search for each seed creator by nickname and inject their notes into notes_by_id.

    Seed creators listed in persona_spec.seed_creators are guaranteed to appear in the
    scored output regardless of whether the main query packs happened to surface them.
    Each seed creator's notes are labelled query_pack='seed_rescue' and query='seed:<nickname>'.
    """
    if not config.seed_creators:
        return 0
    injected = 0
    for nickname in config.seed_creators:
        try:
            data = runner.search(nickname)
            items = data.get("items") if isinstance(data, dict) else []
            for item in (items or [])[:20]:
                note = normalize_note_item(item)
                if not note.note_id:
                    continue
                if note.creator_name.lower().replace(" ", "") != nickname.lower().replace(" ", ""):
                    continue
                if note.note_id in notes_by_id:
                    existing = notes_by_id[note.note_id]
                    if "seed_rescue" not in existing.query_pack:
                        existing.query_pack = ",".join([p for p in existing.query_pack.split(",") if p] + ["seed_rescue"])
                    continue
                note.query = f"seed:{nickname}"
                note.query_pack = "seed_rescue"
                annotate_note(note, config)
                notes_by_id[note.note_id] = note
                injected += 1
        except Exception as exc:
            print(f"[warn] seed rescue failed for '{nickname}': {exc}", file=sys.stderr)
    if injected:
        print(f"[info] seed_rescue: injected {injected} notes for {len(config.seed_creators)} seed creator(s)", file=sys.stderr)
    return injected


def collect_notes(runner: XhsRunner, config: RunConfig, offline: bool) -> tuple[list[Note], dict[str, Any]]:
    limits = SCALE_LIMITS.get(config.scale, V1_LIMITS) if config.mode == "v1" else V0_LIMITS
    notes_by_id: dict[str, Note] = {}
    errors: list[str] = []
    stats: dict[str, Any] = {"packs": OrderedDict(), "queries": OrderedDict()}
    pack_items = list(config.query_packs.items())[: limits.get("max_packs", 1)]
    pack_quota = (limits["max_notes"] // len(pack_items)) if config.mode == "v1" and pack_items else limits["max_notes"]

    for pack_index, (pack_name, pack) in enumerate(pack_items):
        queries = pack.get("queries") or []
        pack_note_ids: set[str] = set()
        pack_new_count = 0
        stats["packs"][pack_name] = {"queries": len(queries), "notes": 0, "purpose": pack.get("purpose", "")}

        for query in queries[: limits.get("max_queries_per_pack", len(queries))]:
            try:
                data = runner.search(query)
            except Exception as exc:
                msg = f"search failed for '{query}': {exc}"
                errors.append(msg)
                print(f"[warn] {msg} — skipping query", file=sys.stderr)
                stats["queries"][query] = {"pack": pack_name, "notes": 0}
                continue
            items = data.get("items") if isinstance(data, dict) else []
            query_count = 0
            for item in (items or [])[: limits["notes_per_query"]]:
                note = normalize_note_item(item)
                if not note.note_id:
                    continue
                note.query = query
                note.query_pack = pack_name
                annotate_note(note, config)
                query_count += 1
                pack_note_ids.add(note.note_id)
                existing = notes_by_id.get(note.note_id)
                if existing:
                    existing.matched_keywords.update(note.matched_keywords)
                    existing.matched_signal_keywords = unique_keep_order(existing.matched_signal_keywords + note.matched_signal_keywords)
                    existing.matched_specificity_markers = unique_keep_order(existing.matched_specificity_markers + note.matched_specificity_markers)
                    # FIX: filter empty strings from split to avoid "" contaminating the list
                    existing_queries = [q for q in existing.query.split(",") if q]
                    if query not in existing_queries:
                        existing.query = ",".join(unique_keep_order(existing_queries + [query]))
                    existing_packs = [p for p in existing.query_pack.split(",") if p]
                    if pack_name not in existing_packs:
                        existing.query_pack = ",".join(unique_keep_order(existing_packs + [pack_name]))
                    existing.initial_score = max(existing.initial_score, note.initial_score)
                    continue
                notes_by_id[note.note_id] = note
                pack_new_count += 1
                if pack_new_count >= pack_quota:
                    break
            stats["queries"][query] = {"pack": pack_name, "notes": query_count}
            if pack_new_count >= pack_quota:
                break

        stats["packs"][pack_name]["notes"] = len(pack_note_ids)
        # Progress output
        total = len(notes_by_id)
        max_notes = limits["max_notes"]
        print(f"[info] pack {pack_index + 1}/{len(pack_items)} {pack_name}: {pack_new_count} new notes (total {total}/{max_notes})", file=sys.stderr)

        if len(notes_by_id) >= limits["max_notes"]:
            break
        if not offline and config.mode == "v1" and pack_index < len(pack_items) - 1:
            time.sleep(limits["sleep_between_pack"])
        elif not offline and config.mode == "v0" and pack_index < len(pack_items) - 1:
            time.sleep(V0_LIMITS["sleep_between_queries"])

    stats["errors"] = errors
    if not offline and config.mode == "v1" and config.seed_creators:
        rescue_seeds(runner, config, notes_by_id)
    return list(notes_by_id.values()), stats


def enrich_notes(runner: XhsRunner, notes: list[Note], config: RunConfig) -> list[str]:
    errors: list[str] = []
    for note in notes:
        try:
            detail = runner.read(note)
            merge_note_detail(note, detail)
            annotate_note(note, config)
        except Exception as exc:
            msg = f"read failed for {note.note_id}: {exc}"
            errors.append(msg)
            print(f"[warn] {msg}", file=sys.stderr)
    return errors


def group_and_select_creators(notes: list[Note], config: RunConfig) -> list[Creator]:
    limits = SCALE_LIMITS.get(config.scale, V1_LIMITS) if config.mode == "v1" else V0_LIMITS
    groups: dict[str, Creator] = {}
    for note in notes:
        # FIX: use note_id as final fallback to avoid key collisions when both id and name are empty
        key = note.creator_id or (f"name:{note.creator_name}" if note.creator_name else f"note:{note.note_id}")
        if key not in groups:
            groups[key] = Creator(key=key, creator_name=note.creator_name, xhs_user_id=note.creator_id)
        creator = groups[key]
        creator.notes.append(note)
        creator.creator_name = creator.creator_name or note.creator_name
        creator.xhs_user_id = creator.xhs_user_id or note.creator_id
    ranked = sorted(groups.values(), key=lambda c: creator_recall_sort_key(c, config), reverse=True)
    return ranked[: limits["max_creators"]]


def creator_recall_sort_key(creator: Creator, config: RunConfig) -> tuple[float, float, int, int]:
    if config.mode == "v0":
        return (len(creator.notes), sum(n.initial_score for n in creator.notes) / max(1, len(creator.notes)), len(creator.notes), sum(n.liked_count for n in creator.notes))
    packs: set[str] = set()
    for note in creator.notes:
        packs.update([p for p in note.query_pack.split(",") if p])
    high_signal = sum(high_signal_score_for_note(note) for note in creator.notes)
    return (len(packs), high_signal, len(creator.notes), sum(n.liked_count for n in creator.notes))


def enrich_creators(runner: XhsRunner, creators: list[Creator]) -> list[str]:
    errors: list[str] = []
    for creator in creators:
        if not creator.xhs_user_id:
            continue
        try:
            user_data = runner.user(creator.xhs_user_id)
            creator.user_payload = user_data if isinstance(user_data, dict) else {}
            normalized = normalize_user(creator.user_payload)
            creator.creator_name = normalized.get("nickname") or creator.creator_name
            creator.bio = normalized.get("bio") or creator.bio
            creator.follower_count = normalized.get("follower_count", creator.follower_count)
            creator.profile_url = normalized.get("profile_url") or creator.profile_url
            creator.xhs_user_id = normalized.get("user_id") or creator.xhs_user_id
        except ProfileUnavailable:
            print(f"[warn] profile_unavailable for {creator.xhs_user_id}; leaving profile fields blank", file=sys.stderr)
        except Exception as exc:
            msg = f"user fetch failed for {creator.xhs_user_id}: {exc}"
            errors.append(msg)
            print(f"[warn] {msg}", file=sys.stderr)
        try:
            creator.recent_notes = normalize_user_posts(runner.user_posts(creator.xhs_user_id))
        except ProfileUnavailable:
            print(f"[warn] profile_unavailable for user-posts {creator.xhs_user_id}; continuing", file=sys.stderr)
        except Exception as exc:
            msg = f"user-posts fetch failed for {creator.xhs_user_id}: {exc}"
            errors.append(msg)
            print(f"[warn] {msg}", file=sys.stderr)
    return errors


def collect_comments(runner: XhsRunner, creators: list[Creator], config: RunConfig) -> list[str]:
    limits = SCALE_LIMITS.get(config.scale, V1_LIMITS) if config.mode == "v1" else V0_LIMITS
    errors: list[str] = []
    notes = [note for creator in creators for note in creator.notes]
    ranked_notes = sorted(notes, key=lambda note: note.initial_score, reverse=True)[: limits["comment_notes"]]
    for note in ranked_notes:
        try:
            note.comments = normalize_comments(runner.comments(note), limits["comments_per_note"])
        except Exception as exc:
            msg = f"comments failed for {note.note_id}: {exc}"
            errors.append(msg)
            print(f"[warn] {msg}", file=sys.stderr)
    return errors


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_creator(creator: Creator, config: RunConfig) -> dict[str, Any]:
    if config.mode == "v0":
        return score_creator_v0(creator, config.pool, config.persona_text)
    return score_creator_v1(creator, config)


def score_creator_v1(creator: Creator, config: RunConfig) -> dict[str, Any]:
    all_note_text = " ".join(text_blob_for_note(note) for note in creator.notes)
    recent_text = " ".join(f"{item.get('title', '')} {item.get('content', '')}" for item in creator.recent_notes)
    comments_text = " ".join(comment["content"] for note in creator.notes for comment in note.comments)
    creator_text = " ".join([creator.bio, all_note_text, recent_text])
    all_text = " ".join([creator_text, comments_text])

    signal_hits = unique_hits(all_text, config.signal_keywords)
    specificity_values = unique_keep_order(
        [value for note in creator.notes for value in note.matched_specificity_markers]
        + detect_specificity_values(creator_text, config.signal_keywords)
    )
    signal_plus_specific = unique_keep_order(signal_hits + specificity_values)
    ordinary_hits = unique_hits(all_text, config.ordinary_terms)
    weighted_hits = len(signal_plus_specific) * 2 + len(ordinary_hits)
    weighted_cap = min(20, len(config.signal_keywords) * 2 + len(config.ordinary_terms))
    persona_score = min(35, round(weighted_hits / max(1, weighted_cap) * 35))

    real_counts = count_terms(creator_text, REALNESS_TERMS)
    ad_counts = count_terms(creator_text, config.anti_signals + HARD_AD_TERMS)
    title_variety = len({note.title for note in creator.notes if note.title} | {n.get("title", "") for n in creator.recent_notes if n.get("title")})
    realness_score = max(0, min(20, len(real_counts) * 2 + min(title_variety, 5) * 2 - min(8, sum(ad_counts.values()) * 2)))

    specificity_score = compute_specificity_score(creator, specificity_values, config)

    comments = [comment for note in creator.notes for comment in note.comments]
    if comments:
        concrete = sum(1 for c in comments if len(c["content"]) >= 8)
        questions = sum(1 for c in comments if "?" in c["content"] or "？" in c["content"] or "请问" in c["content"])
        spam = sum(1 for c in comments for term in SPAM_TERMS if term.lower() in c["content"].lower())
        interaction_score = min(10, round((concrete / max(1, len(comments))) * 7 + min(3, questions)))
        interaction_score = max(0, interaction_score - min(5, spam))
    else:
        interaction_score = 3

    product_terms = ["app", "产品", "工具", "iMessage", "workflow", "效率", "软件", "AI", "独立开发"]
    clear_expression = min(4, sum(1 for note in creator.notes if len(note.content) >= 20))
    stable_tags = min(3, len(unique_keep_order([tag for note in creator.notes for tag in note.tags])))
    natural_product = min(3, len(count_terms(all_note_text + recent_text, product_terms)))
    business_score = max(0, min(10, clear_expression + stable_tags + natural_product - min(5, sum(ad_counts.values()))))

    circle_terms = unique_keep_order(config.target_circles + DEFAULT_CIRCLE_TERMS)
    circle_note_counts = count_terms(creator_text, circle_terms)
    circle_comment_counts = count_terms(comments_text, circle_terms)
    circle_score = min(10, len(circle_note_counts) * 2 + len(circle_comment_counts))
    circle_summary = build_circle_summary(circle_note_counts, circle_comment_counts)

    risk_counts = count_terms(creator_text, config.anti_signals + HARD_AD_TERMS + ["搬运", "纯营销", "刷量"])
    spam_comment_count = sum(1 for c in comments for term in SPAM_TERMS if term.lower() in c["content"].lower())
    risk_deduction = min(20, sum(risk_counts.values()) * 3 + spam_comment_count * 2)

    base_score = persona_score + realness_score + specificity_score + interaction_score + business_score + circle_score
    final_score = max(0, min(100, int(round(base_score - risk_deduction))))
    priority = priority_for(final_score, risk_deduction)

    avg_likes = round(sum(note.liked_count for note in creator.notes) / max(1, len(creator.notes)))
    avg_comments = round(sum(note.comment_count for note in creator.notes) / max(1, len(creator.notes)))
    content_tags = unique_keep_order([tag for note in creator.notes for tag in note.tags] + infer_labels(all_text))
    matched = unique_keep_order(signal_plus_specific + ordinary_hits)
    sample_notes = [format_sample_note(note) for note in creator.notes[:3]]
    discovery_queries = unique_keep_order([q for note in creator.notes for q in note.query.split(",") if q])
    discovery_packs = unique_keep_order([p for note in creator.notes for p in note.query_pack.split(",") if p])
    high_signal_notes = [
        note.title for note in sorted(creator.notes, key=high_signal_score_for_note, reverse=True)
        if high_signal_score_for_note(note) > 0
    ][:5]
    retrieval_reason = build_retrieval_reason(creator)
    risk_reason = build_risk_reason(risk_counts, spam_comment_count, risk_deduction)

    row: dict[str, Any] = {
        "creator_name": creator.creator_name,
        "xhs_user_id": creator.xhs_user_id,
        "profile_url": creator.profile_url,
        "follower_count": creator.follower_count,
        "bio": creator.bio,
        "matched_persona": ",".join(matched),
        "score": final_score,
        "priority": priority,
        "follower_tier": compute_follower_tier(creator.follower_count, avg_likes),
        "content_tags": ",".join(content_tags[:10]),
        "audience_signals": circle_summary,
        "sample_notes": "; ".join(sample_notes),
        "avg_likes": avg_likes,
        "avg_comments": avg_comments,
        "match_reason": f"画像分 {persona_score}/35，真实感 {realness_score}/20，具体度 {specificity_score}/15；命中 {','.join(matched[:8])}",
        "risk_reason": risk_reason,
        "next_action": next_action_for(priority),
        "status": "new",
        "discovery_queries": ",".join(discovery_queries),
        "discovery_packs": ",".join(discovery_packs),
        "high_signal_notes": "; ".join(high_signal_notes),
        "retrieval_reason": retrieval_reason,
        "specificity_signals": ",".join(specificity_values),
        "_risk_deduction": risk_deduction,
        "_recall_sort": creator_recall_sort_key(creator, config),
    }
    return row


def compute_specificity_score(creator: Creator, specificity_values: list[str], config: RunConfig) -> int:
    score = min(9, len(specificity_values) * 3)
    high_signal_count = sum(1 for note in creator.notes if note.matched_signal_keywords or note.matched_specificity_markers)
    if high_signal_count >= 2:
        score += 3
    bio_hits = unique_hits(creator.bio, config.signal_keywords) + detect_specificity_values(creator.bio, config.signal_keywords)
    if bio_hits:
        score += 3
    return min(15, score)


def score_creator_v0(creator: Creator, pool: dict[str, list[str]], persona_text: str) -> dict[str, Any]:
    all_note_text = " ".join(text_blob_for_note(note) for note in creator.notes)
    recent_text = " ".join(f"{item.get('title', '')} {item.get('content', '')}" for item in creator.recent_notes)
    comments_text = " ".join(comment["content"] for note in creator.notes for comment in note.comments)
    creator_text = " ".join([creator.bio, all_note_text, recent_text])
    all_text = " ".join([creator_text, comments_text])
    persona_terms = pool["identity_terms"] + pool["content_terms"] + pool["circle_terms"] + pool["scene_terms"]
    matched = unique_hits(all_text, persona_terms)
    persona_score = min(40, round(len(matched) / max(1, min(len(unique_keep_order(persona_terms)), 10)) * 40))
    real_counts = count_terms(creator_text, REALNESS_TERMS)
    ad_counts = count_terms(creator_text, HARD_AD_TERMS)
    title_variety = len({note.title for note in creator.notes if note.title} | {n.get("title", "") for n in creator.recent_notes if n.get("title")})
    realness_score = max(0, min(20, len(real_counts) * 2 + min(title_variety, 5) * 2 - min(8, sum(ad_counts.values()) * 2)))
    comments = [comment for note in creator.notes for comment in note.comments]
    if comments:
        concrete = sum(1 for c in comments if len(c["content"]) >= 8)
        questions = sum(1 for c in comments if "?" in c["content"] or "？" in c["content"] or "请问" in c["content"])
        spam = sum(1 for c in comments for term in SPAM_TERMS if term.lower() in c["content"].lower())
        interaction_score = max(0, min(15, round((concrete / max(1, len(comments))) * 10 + min(5, questions * 2)) - min(8, spam * 2)))
    else:
        interaction_score = 5
    product_terms = ["app", "产品", "工具", "iMessage", "workflow", "效率", "软件", "AI"]
    business_score = max(0, min(15, min(5, sum(1 for note in creator.notes if len(note.content) >= 20)) + min(5, len(unique_keep_order([tag for note in creator.notes for tag in note.tags]))) + min(5, len(count_terms(all_note_text + recent_text, product_terms))) - min(8, sum(ad_counts.values()) * 2)))
    circle_note_counts = count_terms(creator_text, DEFAULT_CIRCLE_TERMS)
    circle_comment_counts = count_terms(comments_text, DEFAULT_CIRCLE_TERMS)
    circle_score = min(10, len(circle_note_counts) * 2 + len(circle_comment_counts))
    risk_counts = count_terms(creator_text, pool["exclude_terms"] + HARD_AD_TERMS + ["搬运", "纯营销", "刷量"])
    spam_comment_count = sum(1 for c in comments for term in SPAM_TERMS if term.lower() in c["content"].lower())
    risk_deduction = min(20, sum(risk_counts.values()) * 3 + spam_comment_count * 2)
    final_score = max(0, min(100, int(round(persona_score + realness_score + interaction_score + business_score + circle_score - risk_deduction))))
    priority = priority_for(final_score, risk_deduction)
    v0_config = RunConfig("v0", persona_text, {}, OrderedDict(), [], [], [], [], pool)
    row: dict[str, Any] = {
        "creator_name": creator.creator_name,
        "xhs_user_id": creator.xhs_user_id,
        "profile_url": creator.profile_url,
        "follower_count": creator.follower_count,
        "bio": creator.bio,
        "matched_persona": ",".join(matched),
        "score": final_score,
        "priority": priority,
        "content_tags": ",".join(unique_keep_order([tag for note in creator.notes for tag in note.tags] + infer_labels(all_text))[:10]),
        "audience_signals": build_circle_summary(circle_note_counts, circle_comment_counts),
        "sample_notes": "; ".join(format_sample_note(note) for note in creator.notes[:3]),
        "avg_likes": round(sum(note.liked_count for note in creator.notes) / max(1, len(creator.notes))),
        "avg_comments": round(sum(note.comment_count for note in creator.notes) / max(1, len(creator.notes))),
        "match_reason": f"命中 {','.join(matched[:8])}；画像分 {persona_score}/40，真实感 {realness_score}/20",
        "risk_reason": build_risk_reason(risk_counts, spam_comment_count, risk_deduction),
        "next_action": next_action_for(priority),
        "status": "new",
        "_risk_deduction": risk_deduction,
        "_recall_sort": creator_recall_sort_key(creator, v0_config),
    }
    for f in V1_CSV_FIELDS:
        row.setdefault(f, "")
    return row


# ---------------------------------------------------------------------------
# Score helpers
# ---------------------------------------------------------------------------

def build_retrieval_reason(creator: Creator) -> str:
    best = sorted(creator.notes, key=high_signal_score_for_note, reverse=True)
    if not best:
        return "无明显召回证据"
    note = best[0]
    signals = unique_keep_order(note.matched_specificity_markers + note.matched_signal_keywords)
    if signals:
        return f"{note.query_pack}: {note.query} matched {','.join(signals[:5])} note: {note.title}"
    return f"{note.query_pack}: {note.query} retrieved note: {note.title}"


def build_circle_summary(note_counts: Counter, comment_counts: Counter) -> str:
    parts = []
    if comment_counts:
        top = "/".join([term for term, _ in comment_counts.most_common(3)])
        parts.append(f"评论含 {top} 词 {sum(comment_counts.values())} 次")
    if note_counts:
        top = "/".join([term for term, _ in note_counts.most_common(3)])
        parts.append(f"note 提及 {top} {sum(note_counts.values())} 次")
    return "，".join(parts) if parts else "未发现明显圈层代理信号"


def build_risk_reason(risk_counts: Counter, spam_comment_count: int, risk_deduction: int) -> str:
    parts = []
    if risk_counts:
        top = ", ".join(f"{term}x{count}" for term, count in risk_counts.most_common(5))
        parts.append(f"风险词: {top}")
    if spam_comment_count:
        parts.append(f"疑似低质评论 {spam_comment_count} 条")
    if risk_deduction >= 15:
        parts.append("risk_deduction >= 15，强制 Reject")
    return "；".join(parts) if parts else "未发现明显风险"


def priority_for(score: int, risk_deduction: int) -> str:
    if score < 50 or risk_deduction >= 15:
        return "Reject"
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    return "C"


def next_action_for(priority: str) -> str:
    return {
        "A": "优先私信，人工复核最近 5 条内容后进入候选池",
        "B": "继续观察，补看主页和近期互动",
        "C": "低优先级观察，只在候选不足时补充",
        "Reject": "放弃",
    }[priority]


def infer_labels(text: str) -> list[str]:
    labels = []
    mapping = {
        "留学生活": ["留子", "留学生", "留学", "海外生活"],
        "vlog": ["vlog", "日常", "记录"],
        "创业日常": ["创业", "founder", "startup", "build in public"],
        "tech": ["tech", "AI", "app", "独立开发", "SaaS", "CS", "NLP"],
        "科研": ["科研", "ACL", "ICLR", "paper", "PhD"],
        "申请考试": ["GRE", "offer", "申请"],
        "租房": ["租房", "搬家"],
    }
    lower = text.lower()
    for label, terms in mapping.items():
        if any(term.lower() in lower for term in terms):
            labels.append(label)
    return labels


def format_sample_note(note: Note) -> str:
    if note.title and note.note_url:
        return f"{note.title} ({note.note_url})"
    return note.title or note.note_url or note.note_id


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_csv(rows: list[dict[str, Any]], path: Path, fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


# Preferred follower tiers for precision picks (both exact and estimated)
_PRECISION_TIERS = {"1K-5K", "~1K-5K", "5K-10K", "~5K-10K"}
_SECONDARY_TIERS = {"10K-50K", "~10K-50K"}


def write_precision_csv(rows: list[dict[str, Any]], path: Path, fields: list[str]) -> int:
    """Write a precision-filtered subset of rows sorted by follower_tier then score.

    Inclusion rules (all must pass):
    - priority A or B: always included
    - priority C: included only if hits ≥ 2 distinct discovery packs
    - priority Reject: excluded

    Sort order within output:
    1. Preferred tier (1K-5K / ~1K-5K) first, then secondary (5K-10K / ~5K-10K), then others
    2. Score descending within each tier group
    """
    def tier_rank(row: dict) -> int:
        t = row.get("follower_tier", "")
        if t in _PRECISION_TIERS:
            return 0
        if t in _SECONDARY_TIERS:
            return 1
        return 2

    def qualifies(row: dict) -> bool:
        p = row.get("priority", "")
        if p in ("A", "B"):
            return True
        if p == "C":
            packs = [x for x in row.get("discovery_packs", "").split(",") if x]
            return len(set(packs)) >= 2
        return False

    precision = [r for r in rows if qualifies(r)]
    precision.sort(key=lambda r: (tier_rank(r), -coerce_int(r.get("score", 0))))
    write_csv(precision, path, fields)
    return len(precision)


def write_summary(rows: list[dict[str, Any]], path: Path, config: RunConfig, stats: dict[str, Any], notes_count: int) -> None:
    if config.mode == "v1":
        write_summary_v1(rows, path, config, stats, notes_count)
    else:
        write_summary_v0(rows, path, config, stats, notes_count)


def write_summary_v1(rows: list[dict[str, Any]], path: Path, config: RunConfig, stats: dict[str, Any], notes_count: int) -> None:
    priority_counts = Counter(row["priority"] for row in rows)
    lines = [
        "# KOC Candidates Summary", "",
        "## 本次 Persona Spec（确认版）", "", "```yaml",
        yaml.safe_dump(config.raw_spec, allow_unicode=True, sort_keys=False).strip() if yaml else json.dumps(config.raw_spec, ensure_ascii=False, indent=2),
        "```", "", "## 生成的 Query Packs", "",
    ]
    for pack_name, pack in config.query_packs.items():
        lines.append(f"- `{pack_name}`: {pack.get('purpose', '')}；queries: {', '.join(pack.get('queries', []))}")
    lines.extend(["", "## Query Pack 召回统计（含零召回警告）", "", "| Pack | Queries | Notes 召回 |", "|------|---------|-----------|"])
    for pack_name, item in stats.get("packs", {}).items():
        warn = " ⚠️ zero recall" if item.get("notes", 0) == 0 else ""
        lines.append(f"| {pack_name} | {item.get('queries', 0)} | {item.get('notes', 0)}{warn} |")
    zero_queries = [q for q, item in stats.get("queries", {}).items() if item.get("notes", 0) == 0]
    if zero_queries:
        lines.extend(["", f"Zero-recall queries: {', '.join(zero_queries)}"])
    lines.extend([
        "", "## 搜索结果概览", "",
        f"- 去重 note 数: {notes_count}",
        f"- 候选 creator 数: {len(rows)}",
        f"- Priority 分布: {dict(priority_counts)}",
        "", "## Top Creator 召回证据（排序依据：pack diversity + signal score）", "",
    ])
    recall_rows = sorted(rows, key=lambda row: row.get("_recall_sort", (0, 0, 0, 0)), reverse=True)[:10]
    for idx, row in enumerate(recall_rows, 1):
        lines.extend([
            f"### {idx}. {row['creator_name'] or row['xhs_user_id'] or 'Unknown'}", "",
            f"- Discovery packs: {row.get('discovery_packs', '')}",
            f"- Discovery queries: {row.get('discovery_queries', '')}",
            f"- Specificity signals: {row.get('specificity_signals', '')}",
            f"- Retrieval reason: {row.get('retrieval_reason', '')}", "",
        ])
    lines.extend(["## Top 推荐 KOC（排序依据：final score）", ""])
    top_rows = [row for row in rows if row["priority"] != "Reject"][:10]
    if not top_rows:
        lines.append("未发现可推荐候选人。")
    for idx, row in enumerate(top_rows, 1):
        lines.extend([
            f"### {idx}. {row['creator_name'] or row['xhs_user_id'] or 'Unknown'}", "",
            f"- Score: {row['score']} ({row['priority']})",
            f"- Profile: {row['profile_url']}",
            f"- Matched persona: {row['matched_persona']}",
            f"- 推荐理由: {row['match_reason']}",
            f"- 召回理由: {row.get('retrieval_reason', '')}",
            f"- 风险点: {row['risk_reason']}",
            f"- 圈层代理信号: {row['audience_signals']}",
            f"- Sample notes: {row['sample_notes']}",
            f"- Next action: {row['next_action']}", "",
        ])
    reject_rows = [row for row in rows if row["priority"] == "Reject"]
    if reject_rows:
        lines.extend(["## Reject 候选", ""])
        for row in reject_rows[:10]:
            lines.append(f"- {row['creator_name'] or row['xhs_user_id']}: {row['risk_reason']}；{row.get('retrieval_reason', '')}")
        lines.append("")
    lines.extend([
        "## 低可信度说明（圈层代理 + 搜索曝光偏差）", "",
        "圈层代理信号只来自公开内容和评论文本的主题重叠，不能证明粉丝身份。请把它作为人工复核线索，而不是受众画像结论。", "",
        "Xiaohongshu search is algorithmically exposed content, not a full creator database. Low-exposure but high-quality KOCs may require manual discovery through topics, communities, and comment sections.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary_v0(rows: list[dict[str, Any]], path: Path, config: RunConfig, stats: dict[str, Any], notes_count: int) -> None:
    priority_counts = Counter(row["priority"] for row in rows)
    lines = ["# KOC Candidates Summary", "", "## 本次画像总结", "", config.persona_text, "", "## 使用的关键词池", ""]
    for key in ["identity_terms", "content_terms", "circle_terms", "scene_terms", "exclude_terms"]:
        lines.append(f"- `{key}`: {', '.join(config.pool.get(key, []))}")
    lines.extend(["", "## 搜索结果概览", "", f"- 去重 note 数: {notes_count}", f"- 候选 creator 数: {len(rows)}", f"- Priority 分布: {dict(priority_counts)}", "", "## Top 10 推荐 KOC", ""])
    for idx, row in enumerate([r for r in rows if r["priority"] != "Reject"][:10], 1):
        lines.extend([f"### {idx}. {row['creator_name'] or row['xhs_user_id'] or 'Unknown'}", "", f"- Score: {row['score']} ({row['priority']})", f"- 推荐理由: {row['match_reason']}", f"- 风险点: {row['risk_reason']}", ""])
    lines.extend(["## 低可信度说明", "", "圈层代理信号只来自公开内容和评论文本的主题重叠，不能证明粉丝身份。"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_meta(path: Path, run_id: str, config: RunConfig, stats: dict[str, Any],
                   rows: list[dict[str, Any]], notes_count: int, started_at: str,
                   finished_at: str, duration_sec: float, errors: list[str],
                   xhs_user: str) -> None:
    priority_counts = dict(Counter(row["priority"] for row in rows))
    pack_stats = {
        pack_name: {"queries": item.get("queries", 0), "notes": item.get("notes", 0)}
        for pack_name, item in stats.get("packs", {}).items()
    }
    meta = {
        "run_id": run_id,
        "persona_slug": make_slug(config.persona_text),
        "scale": config.scale,
        "mode": config.mode,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": round(duration_sec, 1),
        "notes_collected": notes_count,
        "creators_scored": len(rows),
        "priority_distribution": priority_counts,
        "pack_stats": pack_stats,
        "errors": errors,
        "xhs_user": xhs_user,
    }
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def write_retrospective(path: Path, rows: list[dict[str, Any]], stats: dict[str, Any], config: RunConfig, run_id: str) -> None:
    lines = [f"# Run 复盘 {run_id}", ""]

    # Pack efficiency
    lines.extend(["## Pack 效率分析", "", "| Pack | 召回数 | A/B 候选 | 效率 |", "|------|--------|----------|------|"])
    pack_to_creators: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for pack in [p for p in row.get("discovery_packs", "").split(",") if p]:
            pack_to_creators.setdefault(pack, []).append(row)
    for pack_name, pack_stat in stats.get("packs", {}).items():
        notes_count = pack_stat.get("notes", 0)
        creators = pack_to_creators.get(pack_name, [])
        ab_count = sum(1 for r in creators if r.get("priority") in ("A", "B"))
        if notes_count == 0:
            efficiency = "❌ 零召回"
        elif ab_count == 0:
            efficiency = "低 → 建议调整查询词"
        elif ab_count >= 2:
            efficiency = "高"
        else:
            efficiency = "中"
        lines.append(f"| {pack_name} | {notes_count} | {ab_count} | {efficiency} |")

    # Zero-recall queries
    zero_queries = [q for q, item in stats.get("queries", {}).items() if item.get("notes", 0) == 0]
    if zero_queries:
        lines.extend(["", "## 零召回查询（建议替换）", ""])
        for q in zero_queries:
            lines.append(f"- `{q}` → 0 条结果，建议检查词的小红书热度或改为更本土化表达")

    # Top keywords in A/B creators
    ab_rows = [r for r in rows if r.get("priority") in ("A", "B")]
    if ab_rows:
        kw_counter: Counter = Counter()
        for row in ab_rows:
            for kw in row.get("matched_persona", "").split(","):
                if kw.strip():
                    kw_counter[kw.strip()] += 1
        top_kws = [kw for kw, _ in kw_counter.most_common(8)]
        lines.extend(["", f"## A/B 候选共同命中词（共 {len(ab_rows)} 人）", "", ", ".join(top_kws) if top_kws else "无"])

    # Vocabulary gap: words appearing in Reject notes but not in signal_keywords
    reject_rows = [r for r in rows if r.get("priority") == "Reject"]
    if reject_rows and config.signal_keywords:
        reject_words: Counter = Counter()
        signal_lower = {k.lower() for k in config.signal_keywords}
        for row in reject_rows:
            for kw in row.get("matched_persona", "").split(","):
                kw = kw.strip()
                if kw and kw.lower() not in signal_lower and len(kw) >= 2:
                    reject_words[kw] += 1
        gap_words = [kw for kw, cnt in reject_words.most_common(8) if cnt >= 2]
        if gap_words:
            lines.extend(["", "## 词汇缺口（Reject 候选中高频词，未在 signal_keywords 中）", "", f"`{'`, `'.join(gap_words)}`", "", "建议评估是否加入 signal_keywords 或新建 query pack 覆盖。"])

    # Suggestions
    low_packs = [p for p, item in stats.get("packs", {}).items() if item.get("notes", 0) == 0 or sum(1 for r in pack_to_creators.get(p, []) if r.get("priority") in ("A", "B")) == 0]
    if low_packs or zero_queries:
        lines.extend(["", "## 下次优化建议", ""])
        for pack in low_packs[:3]:
            purpose = (config.query_packs.get(pack) or {}).get("purpose", "")
            lines.append(f"- **{pack}**（{purpose}）：零或低效，建议替换查询词或调整 purpose 方向")
        if zero_queries:
            lines.append(f"- 以下查询词返回 0 结果，建议删除或替换：`{'`, `'.join(zero_queries[:5])}`")

    lines.extend([
        "", "## 说明", "",
        "本复盘基于本次 run 的搜索数据自动生成。小红书搜索结果受算法曝光影响，"
        "不代表全量创作者数据库。低曝光但高质量的 KOC 需通过话题、社区和评论区人工发现。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Validate (dry run)
# ---------------------------------------------------------------------------

def validate_config(config: RunConfig) -> None:
    limits = SCALE_LIMITS.get(config.scale, V1_LIMITS) if config.mode == "v1" else V0_LIMITS
    total_queries = sum(len(pack.get("queries", [])) for pack in config.query_packs.values())
    sleep_calls = limits["sleep_between_calls"]
    sleep_pack = limits.get("sleep_between_pack", limits.get("sleep_between_queries", 10))
    n_packs = len(config.query_packs)
    est_notes = total_queries * limits["notes_per_query"]
    est_time = total_queries * sleep_calls + (n_packs - 1) * sleep_pack + limits["max_notes"] * sleep_calls * 3

    print(f"\n[validate] mode: {config.mode} | scale: {config.scale}")
    print(f"[validate] packs: {n_packs}  |  queries total: {total_queries}")
    print(f"[validate] max notes: {limits['max_notes']}  |  max creators: {limits['max_creators']}")
    print(f"[validate] estimated raw notes (before dedup): ~{est_notes}")
    print(f"[validate] estimated run time: ~{est_time // 60} min")
    print(f"[validate] signal keywords ({len(config.signal_keywords)}): {', '.join(config.signal_keywords[:10])}")
    print(f"[validate] anti-signals ({len(config.anti_signals)}): {', '.join(config.anti_signals[:8])}")
    print()
    for pack_name, pack in config.query_packs.items():
        print(f"  [{pack_name}] {pack.get('purpose', '')}")
        for q in pack.get("queries", []):
            print(f"    - {q}")
    print()


# ---------------------------------------------------------------------------
# Merge runs
# ---------------------------------------------------------------------------

def merge_runs(runs_dir: Path, output_path: Path) -> int:
    """Merge all koc_candidates.csv files under runs_dir, dedup by xhs_user_id, keep highest score."""
    merged: dict[str, dict[str, Any]] = {}
    csv_files = list(runs_dir.glob("**/koc_candidates.csv"))
    if not csv_files:
        print(f"[warn] no koc_candidates.csv found under {runs_dir}", file=sys.stderr)
        return 0
    all_fields: list[str] = []
    for csv_path in sorted(csv_files):
        with csv_path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not all_fields and reader.fieldnames:
                all_fields = list(reader.fieldnames)
            for row in reader:
                uid = row.get("xhs_user_id") or row.get("creator_name", "")
                if not uid:
                    continue
                existing = merged.get(uid)
                if existing is None or coerce_int(row.get("score", 0)) > coerce_int(existing.get("score", 0)):
                    merged[uid] = row
    if not merged:
        return 0
    rows = sorted(merged.values(), key=lambda r: -coerce_int(r.get("score", 0)))
    fields = all_fields or V1_CSV_FIELDS
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    return len(rows)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(
    persona_yaml: Path | None,
    persona_text: str | None,
    offline_json: Path | None,
    output_base: Path,
    scale: str = "normal",
    no_sleep: bool = False,
    validate: bool = False,
    use_run_dir: bool = True,
) -> int:
    config = load_run_config(persona_yaml, persona_text, scale)
    limits = SCALE_LIMITS.get(scale, V1_LIMITS) if config.mode == "v1" else V0_LIMITS

    if validate:
        validate_config(config)
        return 0

    fixture = load_yaml_or_json(offline_json) if offline_json else None
    runner = XhsRunner(offline_fixture=fixture, sleep_calls=not no_sleep, limits=limits)
    runner.check_live_ready()

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    started_at = datetime.now(timezone.utc).isoformat()
    started_ts = time.monotonic()

    if use_run_dir:
        output_dir = make_run_dir(output_base, config, run_id)
    else:
        output_dir = output_base
        output_dir.mkdir(parents=True, exist_ok=True)

    if config.mode == "v1":
        dump_yaml(output_dir / "persona_spec.yaml", config.raw_spec)

    print(f"[info] mode: {config.mode} | scale: {scale} | run: {run_id}", file=sys.stderr)
    print(f"[info] output: {output_dir}", file=sys.stderr)
    print(f"[info] query packs: {json.dumps(config.query_packs, ensure_ascii=False)}", file=sys.stderr)

    all_errors: list[str] = []

    notes, stats = collect_notes(runner, config, offline=fixture is not None)
    errors = enrich_notes(runner, notes, config)
    all_errors.extend(errors)

    creators = group_and_select_creators(notes, config)
    errors = enrich_creators(runner, creators)
    all_errors.extend(errors)

    errors = collect_comments(runner, creators, config)
    all_errors.extend(errors)

    rows = [score_creator(creator, config) for creator in creators]
    rows.sort(key=lambda row: (row["priority"] == "Reject", -coerce_int(row["score"])))

    fields = V1_CSV_FIELDS if config.mode == "v1" else BASE_CSV_FIELDS
    csv_path = output_dir / "koc_candidates.csv"
    precision_csv_path = output_dir / "koc_candidates_precision.csv"
    md_path = output_dir / "koc_candidates_summary.md"
    meta_path = output_dir / "run_meta.json"
    retro_path = output_dir / "retrospective.md"

    write_csv(rows, csv_path, fields)
    if config.mode == "v1":
        n_precision = write_precision_csv(rows, precision_csv_path, fields)
        print(f"[ok] wrote {precision_csv_path} ({n_precision} precision picks)", file=sys.stderr)
    write_summary(rows, md_path, config, stats, len(notes))

    finished_at = datetime.now(timezone.utc).isoformat()
    duration_sec = time.monotonic() - started_ts
    xhs_user = runner.get_authed_user()

    write_run_meta(meta_path, run_id, config, stats, rows, len(notes), started_at, finished_at, duration_sec, all_errors, xhs_user)
    if config.mode == "v1":
        write_retrospective(retro_path, rows, stats, config, run_id)

    print(f"[ok] wrote {csv_path}", file=sys.stderr)
    print(f"[ok] wrote {md_path}", file=sys.stderr)
    print(f"[ok] wrote {meta_path}", file=sys.stderr)
    if config.mode == "v1":
        print(f"[ok] wrote {retro_path}", file=sys.stderr)
        print(f"[ok] wrote {output_dir / 'persona_spec.yaml'}", file=sys.stderr)
    print(f"[done] {len(rows)} creators scored in {duration_sec:.0f}s | {output_dir}", file=sys.stderr)
    print(f"[done] precision picks → {precision_csv_path.name if config.mode == 'v1' else 'n/a (v0 mode)'}", file=sys.stderr)
    session_expired = sum(1 for e in all_errors if "Session expired" in e)
    if session_expired > 0:
        print(
            f"[warn] {session_expired} comments call(s) failed due to session expiry — "
            "audience_signals scores are degraded. Run `xhs login` before the next run.",
            file=sys.stderr,
        )
    return 0
