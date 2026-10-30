#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSS 读写：抓取清洗后的唯一真源。

GitHub Actions 的职责到「产出一份去重整理好的 RSS」为止；
界面（index.html）与推送数据（data.json）都从这份 RSS 二次派生，
不再各自持有切面逻辑，避免三处口径打架。

自定义命名空间 ns/deal 承载结构化字段：
    deal:sourceUrl / deal:vendorUrl / deal:sourceName
    deal:deadline / deal:daysLeft / deal:kind / deal:isNew / deal:srcs
标准字段仍然可读：
    title / link / guid / pubDate / category / description
"""
import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime

NS = "https://yutao8.github.io/ai-deal-radar/ns/deal"
ET.register_namespace("deal", NS)
ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
ATOM = "http://www.w3.org/2005/Atom"


def _cdata(text):
    """description 用 CDATA 包住，避免正文里的 & < 破坏 XML。"""
    t = str(text or "")
    return "<![CDATA[" + t.replace("]]>", "]]&gt;") + "]]>"


def _rfc822(dt):
    return format_datetime(dt.astimezone(timezone.utc))


def write_rss(items, meta, path):
    """items: 已去重整理的活动列表；meta: 频道级信息。"""
    now = meta.get("built_at") or datetime.now(timezone.utc)
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
         'xmlns:deal="%s">' % NS,
         "<channel>",
         "  <title>%s</title>" % html.escape(meta.get("title", "AI 优惠雷达")),
         "  <link>%s</link>" % html.escape(meta.get("site", "")),
         "  <description>%s</description>"
         % html.escape(meta.get("description", "AI 厂商限时活动、免费额度与折扣")),
         "  <language>zh-CN</language>",
         "  <generator>ai-deal-radar</generator>",
         "  <lastBuildDate>%s</lastBuildDate>" % _rfc822(now),
         '  <atom:link href="%s" rel="self" type="application/rss+xml"/>'
         % html.escape(meta.get("self", "")),
         "  <deal:generatedAt>%s</deal:generatedAt>"
         % html.escape(meta.get("generated_at", "")),
         "  <deal:total>%d</deal:total>" % len(items),
         "  <deal:nearDays>%d</deal:nearDays>" % int(meta.get("near_days", 3)),
         "  <deal:expiring>%d</deal:expiring>"
         % sum(1 for x in items if x.get("days_left") is not None
               and 0 <= x["days_left"] <= int(meta.get("near_days", 3))),
         "  <deal:newCount>%d</deal:newCount>" % sum(1 for x in items if x.get("is_new")),
         "  <deal:hasChanges>%s</deal:hasChanges>"
         % ("true" if meta.get("has_changes") else "false"),
         ]

    for it in items:
        link = it.get("link_vendor") or it.get("link_source") or meta.get("site", "")
        L.append("  <item>")
        L.append("    <title>%s</title>" % html.escape(it.get("title", "")))
        L.append("    <link>%s</link>" % html.escape(link))
        L.append('    <guid isPermaLink="false">%s</guid>'
                 % html.escape(it.get("key", "")))
        L.append("    <pubDate>%s</pubDate>" % _rfc822(now))
        if it.get("cat"):
            L.append("    <category>%s</category>" % html.escape(it["cat"]))
        L.append("    <description>%s</description>" % _cdata(it.get("detail", "")))
        if it.get("link_source"):
            L.append("    <deal:sourceUrl>%s</deal:sourceUrl>"
                     % html.escape(it["link_source"]))
        if it.get("link_vendor"):
            L.append("    <deal:vendorUrl>%s</deal:vendorUrl>"
                     % html.escape(it["link_vendor"]))
        L.append("    <deal:sourceName>%s</deal:sourceName>"
                 % html.escape(it.get("src_name", "")))
        if it.get("deadline"):
            L.append("    <deal:deadline>%s</deal:deadline>"
                     % html.escape(it["deadline"]))
        if it.get("days_left") is not None:
            L.append("    <deal:daysLeft>%d</deal:daysLeft>" % it["days_left"])
        L.append("    <deal:kind>%s</deal:kind>" % html.escape(it.get("kind", "")))
        L.append("    <deal:isNew>%s</deal:isNew>"
                 % ("true" if it.get("is_new") else "false"))
        L.append("    <deal:notify>%s</deal:notify>"
                 % ("true" if it.get("notify") else "false"))
        L.append("    <deal:srcs>%s</deal:srcs>"
                 % html.escape(",".join(it.get("srcs") or [])))
        L.append("  </item>")

    L.append("</channel>")
    L.append("</rss>")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return path


def _txt(node, tag):
    el = node.find(tag)
    return (el.text or "").strip() if el is not None else ""


def read_rss(path):
    """返回 (meta, items)，item 字段与写入时一致。"""
    root = ET.parse(path).getroot()
    ch = root.find("channel")
    if ch is None:
        raise ValueError("不是合法的 RSS：缺少 channel")

    def q(tag):
        return "{%s}%s" % (NS, tag)

    def channel_int(tag, default=0):
        v = _txt(ch, q(tag))
        try:
            return int(v)
        except ValueError:
            return default

    meta = {
        "title": _txt(ch, "title"),
        "site": _txt(ch, "link"),
        "description": _txt(ch, "description"),
        "generated_at": _txt(ch, q("generatedAt")),
        "near_days": channel_int("nearDays", 3),
        "total": channel_int("total"),
        "expiring": channel_int("expiring"),
        "new_count": channel_int("newCount"),
        "has_changes": _txt(ch, q("hasChanges")) == "true",
        "last_build": _txt(ch, "lastBuildDate"),
    }
    if meta["last_build"]:
        try:
            meta["built_at"] = parsedate_to_datetime(meta["last_build"]).astimezone(
                timezone.utc)
        except (TypeError, ValueError):
            pass

    items = []
    for node in ch.findall("item"):
        dl_raw = _txt(node, q("daysLeft"))
        items.append({
            "key": _txt(node, "guid"),
            "title": _txt(node, "title"),
            "detail": _txt(node, "description"),
            "cat": _txt(node, "category"),
            "link": _txt(node, "link"),
            "link_source": _txt(node, q("sourceUrl")),
            "link_vendor": _txt(node, q("vendorUrl")),
            "src_name": _txt(node, q("sourceName")),
            "srcs": [s for s in _txt(node, q("srcs")).split(",") if s],
            "deadline": _txt(node, q("deadline")),
            "kind": _txt(node, q("kind")),
            "days_left": int(dl_raw) if re.fullmatch(r"-?\d+", dl_raw) else None,
            "is_new": _txt(node, q("isNew")) == "true",
            "notify": _txt(node, q("notify")) == "true",
        })
    return meta, items
