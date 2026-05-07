#!/usr/bin/env python3
"""Import KOC candidates CSV + MD summary into Feishu Bitable.

Creates:
  - Table 1 "KOC候选人": all CSV rows as records
  - Table 2 "运行说明": MD summary split by section

Prerequisites:
  - lark-cli installed and authenticated (lark-cli auth login)
  - Feishu app has bitable permissions (bitable:app scope)

Usage:
    python3 feishu_import.py --csv <path> --md <path> [--folder-token <token>]
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def lark(method: str, path: str, data: dict | None = None) -> dict:
    """Call Feishu Open API via lark-cli. Returns parsed JSON dict."""
    cmd = ["lark-cli", "api", method, path]
    if data:
        cmd += ["--data", json.dumps(data, ensure_ascii=False)]
    env = {**os.environ, "LARK_CLI_NO_PROXY": "1"}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    # lark-cli writes JSON to stdout on success; on error it goes to stderr
    raw = result.stdout.strip() or result.stderr.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [err] {method} {path}: {raw[:150]}", file=sys.stderr)
        return {}


def put_field(app_token: str, table_id: str, field_id: str, name: str, ftype: int,
              prop: dict | None = None) -> bool:
    """Rename/update a field using PUT (PATCH returns 404 on Feishu)."""
    body: dict = {"field_name": name, "type": ftype}
    if prop:
        body["property"] = prop
    resp = lark("PUT", f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}", body)
    return resp.get("code") == 0


def create_field(app_token: str, table_id: str, name: str, ftype: int,
                 prop: dict | None = None) -> str | None:
    """Create a new field and return its field_id."""
    body: dict = {"field_name": name, "type": ftype}
    if prop:
        body["property"] = prop
    resp = lark("POST", f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields", body)
    return resp.get("data", {}).get("field", {}).get("field_id")


def delete_field(app_token: str, table_id: str, field_id: str) -> None:
    lark("DELETE", f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}")


def setup_koc_table(app_token: str, table_id: str,
                    primary_id: str, singlesel_id: str,
                    extra_field_ids: list[str]) -> None:
    """Configure default table fields for KOC candidates."""
    print("  Renaming primary field...")
    put_field(app_token, table_id, primary_id, "创作者昵称", 1)

    print("  Configuring 优先级 field...")
    put_field(app_token, table_id, singlesel_id, "优先级", 3,
              {"options": [{"name": "A", "color": 1}, {"name": "B", "color": 2},
                           {"name": "C", "color": 3}, {"name": "Reject", "color": 0}]})

    print("  Deleting default unused fields...")
    for fid in extra_field_ids:
        delete_field(app_token, table_id, fid)
        time.sleep(0.05)

    print("  Creating data fields...")
    new_fields: list[tuple] = [
        ("评分",      2, None),
        ("粉丝数",    2, None),
        ("小红书主页", 15, None),
        ("小红书ID",  1, None),
        ("画像匹配",  1, None),
        ("内容标签",  1, None),
        ("匹配理由",  1, None),
        ("圈层信号",  1, None),
        ("风险点",    1, None),
        ("下一步行动", 1, None),
        ("状态",     3, {"options": [{"name": "待联系"}, {"name": "已联系"},
                                     {"name": "跟进中"}, {"name": "已合作"}, {"name": "不适合"}]}),
        ("简介",      1, None),
        ("平均点赞",  2, None),
        ("平均评论",  2, None),
        ("示例笔记",  1, None),
        ("发现词包",  1, None),
        ("召回理由",  1, None),
    ]
    for name, ftype, prop in new_fields:
        create_field(app_token, table_id, name, ftype, prop)
        time.sleep(0.1)


def build_record(row: dict) -> dict:
    def t(k: str) -> str: return row.get(k, "").strip()
    def n(k: str) -> float | None:
        v = row.get(k, "").strip().replace(",", "")
        try: return float(v) if v else None
        except ValueError: return None

    fields: dict = {
        "创作者昵称":  t("creator_name"),
        "优先级":     t("priority") or None,
        "评分":       n("score"),
        "粉丝数":     n("follower_count"),
        "小红书ID":   t("xhs_user_id"),
        "画像匹配":   t("matched_persona"),
        "内容标签":   t("content_tags"),
        "匹配理由":   t("match_reason"),
        "圈层信号":   t("audience_signals"),
        "风险点":     t("risk_reason"),
        "下一步行动": t("next_action"),
        "状态":       "待联系" if t("priority") in ("A", "B") else None,
        "简介":       t("bio"),
        "平均点赞":   n("avg_likes"),
        "平均评论":   n("avg_comments"),
        "示例笔记":   t("sample_notes"),
        "发现词包":   t("discovery_packs"),
        "召回理由":   t("retrieval_reason"),
    }
    url = t("profile_url")
    if url:
        fields["小红书主页"] = {"link": url, "text": "小红书主页"}
    return {k: v for k, v in fields.items() if v is not None and v != ""}


def insert_csv_records(app_token: str, table_id: str, csv_path: Path) -> int:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"  Inserting {len(rows)} records...")
    records = [{"fields": build_record(r)} for r in rows]
    total = 0
    for i in range(0, len(records), 100):
        batch = records[i:i + 100]
        resp = lark("POST",
                    f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
                    {"records": batch})
        n = len(resp.get("data", {}).get("records", []))
        code = resp.get("code", -1)
        if code != 0:
            print(f"  [warn] batch {i//100+1} code={code} msg={resp.get('msg')}", file=sys.stderr)
        total += n
        time.sleep(0.3)
    return total


def insert_md_summary(app_token: str, table_id: str, md_path: Path) -> int:
    content = md_path.read_text(encoding="utf-8")
    sections = [("## " + s).strip() if not s.startswith("#") else s.strip()
                for s in content.split("\n## ") if s.strip()]
    records = [{"fields": {"内容": s[:5000]}} for s in sections]
    if not records:
        return 0
    resp = lark("POST",
                f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
                {"records": records})
    return len(resp.get("data", {}).get("records", []))


def create_bitable(folder_token: str, name: str) -> tuple[str, str]:
    resp = lark("POST", "/open-apis/bitable/v1/apps",
                {"name": name, "folder_token": folder_token})
    app = resp.get("data", {}).get("app", {})
    return app.get("app_token", ""), app.get("default_table_id", "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to koc_candidates.csv")
    parser.add_argument("--md", required=True, help="Path to koc_candidates_summary.md")
    parser.add_argument("--folder-token", default="", help="Feishu folder token (empty = root)")
    parser.add_argument("--app-token", default="", help="Reuse existing Bitable app_token")
    parser.add_argument("--table-id", default="", help="Reuse existing table_id")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    md_path = Path(args.md)

    if args.app_token and args.table_id:
        app_token, table_id = args.app_token, args.table_id
        print(f"Reusing Bitable: {app_token} / {table_id}")
    else:
        print("[1/5] Creating Bitable document...")
        app_token, table_id = create_bitable(args.folder_token, "KOC候选人追踪")
        if not app_token:
            print("[error] Failed to create Bitable", file=sys.stderr)
            sys.exit(1)
        print(f"  app_token={app_token}  table_id={table_id}")

        print("[2/5] Getting default table fields...")
        resp = lark("GET", f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
        fields = resp.get("data", {}).get("items", [])
        primary_id = next((f["field_id"] for f in fields if f.get("is_primary")), "")
        singlesel_id = next((f["field_id"] for f in fields if f.get("ui_type") == "SingleSelect"), "")
        extra_ids = [f["field_id"] for f in fields
                     if not f.get("is_primary") and f.get("ui_type") != "SingleSelect"]

        print("[3/5] Setting up KOC table schema...")
        setup_koc_table(app_token, table_id, primary_id, singlesel_id, extra_ids)

    print("[4/5] Inserting KOC candidate records...")
    n = insert_csv_records(app_token, table_id, csv_path)
    print(f"  inserted {n} records")

    print("[5/5] Creating summary table...")
    resp = lark("POST", f"/open-apis/bitable/v1/apps/{app_token}/tables",
                {"table": {"name": "运行说明", "fields": [{"field_name": "内容", "type": 1}]}})
    summary_table_id = resp.get("data", {}).get("table_id")
    if summary_table_id:
        n = insert_md_summary(app_token, summary_table_id, md_path)
        print(f"  inserted {n} summary sections")

    print()
    print(f"Done! Open: https://fcno6t1gx32s.feishu.cn/base/{app_token}")


if __name__ == "__main__":
    main()
