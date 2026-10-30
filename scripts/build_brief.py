#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 优惠雷达 · S3 文案生成器

流水线三步，每步都留产物：

    S1 采集    scripts/check_deals.py  → docs/stages/01_raw.json    全量原始（含跨源重复）
    S2 筛选去重 同上（merge_dups）      → docs/stages/02_active.json 当前有效 + 跨站去重
    S3 文案    本文件                   → docs/stages/03_brief.json + docs/brief.txt

本文件只消费 S2 的结论（payload 里的 new_deals / expiring_new / new_resources），
不抓取、不判断活动是否有效、不合并条目。下游推送端只读 S3 的 brief 原文，一字不发第二遍。
"""

import re
from datetime import datetime, timedelta, timezone

CN = timezone(timedelta(hours=8))
LIMIT = 1500

BLOCKS = [
    ("新活动", "new_deals"),
    ("即将截止", "expiring_new"),
    ("新增免费资源", "new_resources"),
]


def _link(item):
    """厂商原链优先，退回来源链接。不拼接、不追加任何参数。"""
    for f in ("link_vendor", "link_source"):
        v = (item.get(f) or "").strip()
        if v:
            return v
    return ""


def _days(item):
    d = item.get("days_left")
    try:
        return int(d)
    except (TypeError, ValueError):
        return None


def _deadline_tag(item):
    d = _days(item)
    if d is None:
        return ""
    if d < 0:
        return "已截止"
    if d == 0:
        return "今天截止"
    return "剩 %d 天" % d


def _prio(item, base):
    """超字数时的牺牲顺序：数字越大越先删。"""
    d = _days(item)
    if d is None:
        return 2
    if d <= 0:
        return 0
    if d == 1:
        return 1
    return max(3, base)


def _squash(s, n=80):
    """单行化并限长，避免一条活动把整屏吃掉。"""
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _rows(payload):
    seen, out = set(), []
    for label, field in BLOCKS:
        for it in payload.get(field) or []:
            key = it.get("key") or (it.get("title"), _link(it))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "block": label,
                "prio": _prio(it, 3 if label == "即将截止" else 2),
                "title": _squash(it.get("title")),
                "tag": _deadline_tag(it),
                "link": _link(it),
            })
    return out


def _render(rows, header, failed, dropped=0):
    parts = [header]
    for label, _f in BLOCKS:
        lines = [r for r in rows if r["block"] == label]
        if not lines:
            continue
        parts.append("")
        parts.append("■ " + label)
        for r in lines:
            seg = [r["title"]]
            if r["tag"]:
                seg.append(r["tag"])
            if r["link"]:
                seg.append(r["link"])
            parts.append(" ｜ ".join(seg))
    if dropped:
        parts.extend(["", "另有 %d 条略" % dropped])
    if failed:
        parts.extend(["", "⚠ 来源异常：" + "、".join(failed) + "，本次结果可能不完整"])
    return "\n".join(parts).strip()


def compose(payload, limit=LIMIT):
    """S2 结论 → 手机可读文案。返回 (text, meta)。"""
    gen = (payload.get("generated_at") or "").strip()
    try:
        header = "【AI 优惠雷达】" + datetime.fromisoformat(gen).astimezone(CN).strftime("%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        header = "【AI 优惠雷达】" + (payload.get("generated_date") or "")

    failed = [f.get("name") or f.get("source") for f in (payload.get("failed_sources") or [])]
    failed = [f for f in failed if f]

    rows = _rows(payload)
    if not rows:
        text = header + "\n\n本次无新增活动，也无新进入提醒窗口的截止条目。"
        return text, {"chars": len(text), "dropped": 0, "items": 0, "limit": limit}

    order = {label: i for i, (label, _f) in enumerate(BLOCKS)}
    keep = sorted(rows, key=lambda r: (r["prio"], order[r["block"]]))
    text, dropped = _render(keep, header, failed), 0
    while len(text) > limit and len(keep) > 1:
        victim = max(range(len(keep)), key=lambda i: (keep[i]["prio"], i))
        keep.pop(victim)
        dropped += 1
        text = _render(keep, header, failed, dropped)

    blocks = {}
    for label, _f in BLOCKS:
        n = len([r for r in keep if r["block"] == label])
        if n:
            blocks[label] = n

    return text, {
        "chars": len(text),
        "dropped": dropped,
        "items": len(keep),
        "blocks": blocks,
        "limit": limit,
    }


if __name__ == "__main__":
    import json
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "docs", "data.json")
    with open(path, encoding="utf-8") as f:
        text, meta = compose(json.load(f))
    print(text)
    print("\n--- meta ---")
    print(json.dumps(meta, ensure_ascii=False))
