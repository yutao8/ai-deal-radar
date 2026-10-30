#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 优惠雷达 · 数据采集器

七个来源：
    限时活动类（有截止日期）
      S1  aitkradar.cn/deals.xml                    RSS 2.0
      S2  apiprice.app/zh/deals/                    JSON-LD ItemList
      S3  devtk.ai/zh/deals/                        SSR HTML 卡片
      S6  token-fbi.com/data.json                   结构化数据集
      S7  tokentab.cn/assets/js/deals-core.js       UMD 数据内核（需 node）
    长期免费资源类
      S4  github panxunying/ai-coding-welfare       sites.json
      S5  github guihuashaoxiang/FreeLLM-API-KeyHub README.md

每条活动输出两类链接：
    link_source  来源链接 —— 在哪个聚合站看到这条活动，指向该站信息页
    link_vendor  厂商原链 —— 厂商自己的活动页/产品页/官方文档
两者都会剥掉推荐码与追踪参数（详见 urlkit.py）。

用法:
    python scripts/check_deals.py            # 正常跑，无变化返回 10
    python scripts/check_deals.py --ci       # CI 模式，恒返回 0
    python scripts/check_deals.py --no-update --near-days 3
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urlkit import pair_links, sanitize_url, is_aggregator  # noqa: E402
import rss_io  # noqa: E402
import build_site  # noqa: E402
import build_brief  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "data", "state.json")
DOCS = os.path.join(ROOT, "docs")
DATA_JSON = os.path.join(DOCS, "data.json")
CATALOG_JSON = os.path.join(DOCS, "catalog.json")
RSS_PATH = os.path.join(DOCS, "deals.xml")
REPORT_MD = os.path.join(DOCS, "latest.md")
BRIEF_TXT = os.path.join(DOCS, "brief.txt")
STAGES = os.path.join(DOCS, "stages")
CACHE = os.path.join(ROOT, "data", ".cache")
CN = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

NEAR_DAYS = 3
UPDATE = True
CI = False
for i, a in enumerate(sys.argv):
    if a == "--near-days" and i + 1 < len(sys.argv):
        NEAR_DAYS = int(sys.argv[i + 1])
    if a == "--no-update":
        UPDATE = False
    if a == "--ci":
        CI = True

S1, S2, S3, S4, S5, S6, S7 = ("aitkradar", "apiprice", "devtk",
                              "welfare", "freehub", "tokfbi", "tokentab")
NAME = {
    S1: "AI价格雷达",
    S2: "apiprice",
    S3: "DevTk.AI",
    S4: "ai-coding-welfare",
    S5: "FreeLLM-API-KeyHub",
    S6: "Token FBI",
    S7: "TokenTab 次元塔",
}
PAGE = {
    S1: "https://aitkradar.cn/deals.xml",
    S2: "https://apiprice.app/zh/deals/",
    S3: "https://devtk.ai/zh/deals/",
    S4: "https://github.com/panxunying/ai-coding-welfare",
    S5: "https://github.com/guihuashaoxiang/FreeLLM-API-KeyHub",
    S6: "https://token-fbi.com/table/",
    S7: "https://www.tokentab.cn/deals.html",
}


# ------------------------------------------------------------------ utils
def http_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(s):
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def norm(s):
    return re.sub(r"[\s\-—_]+", "", s or "").lower()


def fix_date(y, m, d):
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return ""


def guess_deadline(text, today):
    full = re.findall(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if full:
        return fix_date(*full[0])
    for m, d in re.findall(r"(?<!\d)(\d{1,2})[-/月](\d{1,2})(?!\d)", text):
        for y in (today.year, today.year + 1):
            v = fix_date(y, m, d)
            if v:
                try:
                    if 0 <= (date.fromisoformat(v) - today).days <= 400:
                        return v
                except ValueError:
                    pass
    return ""


def clean_title(t):
    """去掉「MiniMax：MiniMax …」这类重复的厂牌前缀，只影响展示，不影响 key。"""
    t = (t or "").strip()
    m = re.match(r"^([^：:]{1,12})[：:]\s*(.+)$", t)
    if not m:
        return t
    pre, rest = m.group(1), m.group(2)
    base = re.sub(r"[（(].*?[）)]", "", pre).strip()
    if base and rest.lower().startswith(base.lower()):
        return rest.strip()
    return t


def _rec(**kw):
    """统一字段，缺省值补齐。"""
    rec = {
        "key": "", "src": "", "kind": "deal", "title": "", "cat": "",
        "detail": "", "deadline": "", "basis": "",
        "link_source": "", "link_vendor": "",
    }
    rec.update(kw)
    rec["title"] = clean_title(rec["title"])
    return rec


# ------------------------------------------------------------------ S1 RSS
def parse_s1(text, today):
    out = []
    for b in re.findall(r"<item>(.*?)</item>", text, re.S):
        def t(n):
            m = re.search(r"<" + n + r"[^>]*>(.*?)</" + n + r">", b, re.S)
            return strip_tags(m.group(1)) if m else ""
        desc = t("description")
        parts = [p.strip() for p in desc.split("｜")]
        kind = parts[0] if parts else ""
        detail = parts[1] if len(parts) > 1 else ""
        basis = next((p[3:].strip() for p in parts if p.startswith("依据：")), "")
        m = re.search(r"截止：(\d{4}-\d{2}-\d{2})", desc)
        link = t("link") or t("guid")
        ls, lv = pair_links([link], [basis], PAGE[S1])
        out.append(_rec(
            key=f"{S1}:{t('guid') or link}", src=S1, kind="deal",
            title=t("title"), cat=kind, detail=detail,
            deadline=m.group(1) if m else "", basis=basis,
            link_source=ls, link_vendor=lv,
        ))
    return out


# ------------------------------------------------------------------ S2 JSON-LD
def parse_s2(html, today):
    out = []
    for raw in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                          html, re.S):
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if node.get("@type") != "ItemList":
                continue
            for el in node.get("itemListElement", []):
                it = el.get("item", {})
                title = strip_tags(it.get("name", ""))
                if not title:
                    continue
                desc = strip_tags(it.get("description", ""))
                dl = ""
                vt = [p.get("validThrough") for p in it.get("priceSpecification", [])
                      if p.get("validThrough")]
                if vt:
                    dl = max(vt)[:10]
                if not dl:
                    m = re.search(r"(?:到|至|截止|到期)[^\d]{0,3}"
                                  r"(20\d{2}-\d{2}-\d{2}|\d{1,2}-\d{1,2})", title + " " + desc)
                    if m:
                        dl = guess_deadline(m.group(1), today)
                ls, lv = pair_links([el.get("url"), it.get("@id")],
                                    [it.get("url"), el.get("url")], PAGE[S2])
                out.append(_rec(
                    key=f"{S2}:{it.get('@id') or el.get('url') or norm(title)}",
                    src=S2, kind="deal", title=title,
                    cat=it.get("category") or "", detail=desc, deadline=dl,
                    basis=it.get("url") or "",
                    link_source=ls, link_vendor=lv,
                ))
    return out


# ------------------------------------------------------------------ S3 HTML cards
def parse_s3(html, today):
    out = []
    body = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    for c in re.split(r'<div class="group flex flex-col rounded-xl', body)[1:]:
        h3 = re.search(r"<h3[^>]*>(.*?)</h3>", c, re.S)
        if not h3:
            continue
        title = strip_tags(h3.group(1))
        if not title:
            continue
        cat = ""
        m = re.search(r'<span class="inline-flex shrink-0 items-center rounded-full[^"]*"[^>]*>(.*?)</span>',
                      c, re.S)
        if m:
            cat = strip_tags(m.group(1))
        detail = ""
        for pat in (r'<p class="text-sm font-medium text-emerald-900[^"]*"[^>]*>(.*?)</p>',
                    r'<p class="mb-3 line-clamp-3[^"]*"[^>]*>(.*?)</p>'):
            m = re.search(pat, c, re.S)
            if m:
                detail = strip_tags(m.group(1))
                break
        m = re.search(r"截止\s*(\d{4}-\d{2}-\d{2})", c)
        dl = m.group(1) if m else ""
        nofollow, cta = [], []
        for m2 in re.finditer(r'<a[^>]*href="(https?://[^"]+)"([^>]*)>', c):
            href, attrs = m2.group(1), m2.group(2)
            if "nofollow" in attrs:
                nofollow.append(href)
            elif is_aggregator(href) is False:
                cta.append(href)
        ls, lv = pair_links([PAGE[S3]], cta + nofollow, PAGE[S3])
        out.append(_rec(
            key=f"{S3}:{norm(title)}", src=S3, kind="deal",
            title=title, cat=cat, detail=detail, deadline=dl,
            basis=(nofollow[0] if nofollow else ""),
            link_source=ls, link_vendor=lv,
        ))
    return out


# ------------------------------------------------------------------ S4 GitHub JSON
S4_SITES = "https://raw.githubusercontent.com/panxunying/ai-coding-welfare/main/data/sites.json"
S4_LOG = "https://raw.githubusercontent.com/panxunying/ai-coding-welfare/main/data/changelog.json"


def credits_text(cr):
    if not isinstance(cr, dict):
        return ""
    bits = []
    if cr.get("signup"):
        bits.append(f"注册 {cr['signup']}")
    if cr.get("invite"):
        bits.append(f"邀请 {cr['invite']}")
    if cr.get("dailyCheckin"):
        bits.append(f"签到 {cr['dailyCheckin']}")
    if cr.get("dailyNote"):
        bits.append(str(cr["dailyNote"]))
    unit = cr.get("unit") or ""
    return ("／".join(bits) + (f"（{unit}）" if bits and unit else "")).strip()


def parse_s4(today):
    recs, events = [], []
    data = json.loads(http_get(S4_SITES))
    for s in data.get("sites", []):
        sid = s.get("id") or norm(s.get("name", ""))
        if not sid:
            continue
        detail = strip_tags(s.get("subtitle") or "")
        cr = credits_text(s.get("credits"))
        if cr:
            detail = (detail + "｜额度：" + cr).strip("｜")
        tags = "、".join(s.get("tags") or [])[:60]
        hu, su = s.get("homeUrl") or "", s.get("signupUrl") or ""
        ls, lv = pair_links([PAGE[S4]], [hu, su], PAGE[S4])
        recs.append(_rec(
            key=f"{S4}:site:{sid}", src=S4, kind="res",
            title=s.get("name") or sid, cat=tags or "免费站",
            detail=detail, deadline="", basis=hu,
            link_source=ls, link_vendor=lv,
        ))
    try:
        log = json.loads(http_get(S4_LOG))
        for e in log.get("events", []):
            events.append({
                "at": e.get("at", ""),
                "type": e.get("type", ""),
                "text": strip_tags(e.get("text", "")),
                "severity": e.get("severity", ""),
            })
    except Exception:
        pass
    return recs, events


# ------------------------------------------------------------------ S5 GitHub Markdown
S5_README = "https://raw.githubusercontent.com/guihuashaoxiang/FreeLLM-API-KeyHub/main/README.md"
SEC_RE = re.compile(r"^###\s+(?:\d+\.\s*)?(.+?)\s*$", re.M)
MD_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)|(https?://[^\s)\]>]+)")


def parse_s5(today):
    out = []
    text = http_get(S5_README)
    body = text.split("## 致谢")[0]
    heads = list(SEC_RE.finditer(body))
    for i, m in enumerate(heads):
        name = strip_tags(m.group(1)).strip("*# ")
        if not name or len(name) > 40:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        chunk = body[m.end():end]
        summary = ""
        for para in chunk.split("\n"):
            p = para.strip()
            if not p or p.startswith(("|", ">", "#", "---", "!", "<")):
                continue
            summary = strip_tags(p)
            if len(summary) > 12:
                break
        candidates = [a or b for a, b in MD_LINK_RE.findall(chunk)]
        ls, lv = pair_links([PAGE[S5]], candidates, PAGE[S5])
        out.append(_rec(
            key=f"{S5}:{norm(name)}", src=S5, kind="res",
            title=name, cat="免费额度", detail=summary[:150],
            deadline="", basis="",
            link_source=ls, link_vendor=lv,
        ))
    return out


# ------------------------------------------------------------------ S6 JSON 数据集
S6_DATA = "https://token-fbi.com/data.json"


def parse_s6(today):
    out = []
    d = json.loads(http_get(S6_DATA))
    for it in d.get("items", []):
        name = strip_tags(it.get("name") or "")
        if not name:
            continue
        vendor = (it.get("vendor") or "").strip()
        ftype = (it.get("free_type") or "").strip()
        quota = strip_tags(it.get("quota") or "")
        val = (it.get("validity") or "").strip()
        dl = ""
        m = re.search(r"20\d{2}-\d{2}-\d{2}", val)
        if m:
            dl = m.group(0)
        elif val and not re.search(r"长期|每日|以平台|不定期|暂无", val):
            dl = guess_deadline(val, today)
        cat = "·".join(x for x in (vendor, ftype) if x)
        srcs = it.get("source_urls") or []
        entry, intel = it.get("entry_url") or "", it.get("intel_url") or ""
        ls, lv = pair_links([PAGE[S6]], [entry, intel] + list(srcs), PAGE[S6])
        out.append(_rec(
            key=f"{S6}:{norm(name)}", src=S6, kind="deal" if dl else "res",
            title=name, cat=cat, detail=quota[:220], deadline=dl,
            basis=(srcs[0] if srcs else ""),
            link_source=ls, link_vendor=lv,
        ))
    return out


# ------------------------------------------------------------------ S7 JS 数据内核
S7_JS = "https://www.tokentab.cn/assets/js/deals-core.js"
GRP_CN = {"AGENT": "Agent/编程助手", "MODEL": "大模型 API", "GLOBAL": "海外"}


def parse_s7(today):
    """页面由 deals-core.js 渲染，该文件是 UMD 模块，用 node 取数最稳。"""
    js = http_get(S7_JS)
    if "AGENT" not in js:
        raise RuntimeError("数据文件结构变化")
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "_tt_core.js")
    with open(p, "w", encoding="utf-8") as f:
        f.write(js)
    code = (
        "const c=require('%s');"
        "[['AGENT',c.AGENT],['MODEL',c.MODEL],['GLOBAL',c.GLOBAL]]"
        ".forEach(([g,a])=>(a||[]).forEach(x=>{x.grp=g}));"
        "process.stdout.write(JSON.stringify({u:c.UPDATED,"
        "all:[].concat(c.AGENT||[],c.MODEL||[],c.GLOBAL||[])}));"
    ) % pathlib.Path(p).as_posix()
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("node 解析失败：" + (r.stderr or "")[:120].replace("\n", " "))
    data = json.loads(r.stdout or "{}")
    out = []
    for it in data.get("all", []):
        title = strip_tags(it.get("title") or "")
        if not title:
            continue
        iid = it.get("id") or norm(title)
        bits = [strip_tags(it.get("amount") or ""), strip_tags(it.get("note") or "")]
        detail = "｜".join(x for x in bits if x)
        cat = GRP_CN.get(it.get("grp"), it.get("grp") or "")
        if it.get("perm"):
            cat = "永久免费·" + cat
        dl = (it.get("deadline") or "")[:10]
        ls, lv = pair_links([PAGE[S7]], [it.get("url") or ""], PAGE[S7])
        out.append(_rec(
            key=f"{S7}:{iid}", src=S7, title=title, cat=cat,
            detail=detail[:200], deadline=dl,
            kind="deal" if dl else "res",
            link_source=ls, link_vendor=lv,
        ))
    return out


# ------------------------------------------------------------------ 去重合并
def _bigrams(s):
    s = re.sub(r"[\s\W_]+", "", s.lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _jac(a, b):
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def merge_dups(items, thresh=0.5):
    """同一截止日下标题高度相似的条目视为同一活动，合并并记录全部来源。"""
    used, out = set(), []
    for i, a in enumerate(items):
        if i in used:
            continue
        used.add(i)
        group = [a]
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            b = items[j]
            if a.get("deadline") != b.get("deadline"):
                continue
            if _jac(a["title"], b["title"]) >= thresh:
                group.append(b)
                used.add(j)
        rec = dict(group[0])
        rec["srcs"] = sorted({g["src"] for g in group})
        rec["keys"] = [g["key"] for g in group]
        if len(group) > 1:
            rec["title"] = max((g["title"] for g in group), key=len)
        # 合并时补全缺失的链接，宁可多一条来源也不丢厂商原链
        for field in ("link_source", "link_vendor", "detail", "basis"):
            if not rec.get(field):
                rec[field] = next((g[field] for g in group if g.get(field)), "")
        out.append(rec)
    return out


# ------------------------------------------------------------------ main
def main():
    now = datetime.now(CN)
    today = now.date()
    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            pass
    known = state.get("known", {})
    notified = state.get("expiring_notified", {})
    last_run = state.get("last_run")
    first_baseline = not known

    records, events, fails = [], [], []
    jobs = [
        (S1, lambda: parse_s1(http_get("https://aitkradar.cn/deals.xml"), today)),
        (S2, lambda: parse_s2(http_get("https://apiprice.app/zh/deals/"), today)),
        (S3, lambda: parse_s3(http_get("https://devtk.ai/zh/deals/"), today)),
        (S4, None),
        (S5, lambda: parse_s5(today)),
        (S6, lambda: parse_s6(today)),
        (S7, lambda: parse_s7(today)),
    ]
    for sid, fn in jobs:
        try:
            if sid == S4:
                r, ev = parse_s4(today)
                records.extend(r)
                events.extend(ev)
            else:
                r = fn()
                if not r:
                    fails.append((sid, "解析到 0 条，疑似页面结构变动"))
                records.extend(r)
        except urllib.error.HTTPError as e:
            fails.append((sid, f"HTTP {e.code}"))
        except Exception as e:
            fails.append((sid, f"{type(e).__name__}: {e}"))

    if not records:
        print("## 全部来源拉取失败\n")
        for sid, why in fails:
            print(f"- {NAME.get(sid, sid)}：{why}")
        print("\n基线未改动，下次运行重试。")
        # 全源失败一律让运行变红：CI 里静默返回 0 会让「数据没更新」看起来像「今天没变化」
        return 3

    seen, uniq = set(), []
    for r in records:
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        uniq.append(r)
    for it in uniq:
        it["kind"] = "deal" if it.get("deadline") else "res"

    new_items, exp_all, exp_hit = [], [], []
    for it in uniq:
        if it["key"] not in known:
            new_items.append(it)
        if it["deadline"]:
            try:
                left = (date.fromisoformat(it["deadline"]) - today).days
            except ValueError:
                continue
            if 0 <= left <= NEAR_DAYS:
                it["days_left"] = left
                exp_all.append(it)
                prev = notified.get(it["key"])
                if prev is None or (left == 0 and prev != 0):
                    exp_hit.append(it)
    exp_all.sort(key=lambda x: (x["days_left"], x["title"]))
    exp_hit.sort(key=lambda x: (x["days_left"], x["title"]))
    new_keys = {x["key"] for x in new_items}
    exp_only = [x for x in exp_hit if x["key"] not in new_keys]

    fresh_events = []
    if last_run and events:
        try:
            since = datetime.fromisoformat(last_run)
            for e in events:
                try:
                    at = datetime.fromisoformat(e["at"].replace("Z", "+00:00"))
                except ValueError:
                    continue
                if at > since and e["text"]:
                    fresh_events.append(e)
        except ValueError:
            fresh_events = []
    fresh_events = fresh_events[:15]

    new_deals = [x for x in new_items if x["kind"] == "deal"]
    new_res = [x for x in new_items if x["kind"] == "res"]

    # 报告里的「在架」必须和 data.json 的 counts.total 同一口径（跨站合并后），
    # 否则会出现 report_md 写 290、counts.total 写 258 的矛盾。
    shelf_count = len(merge_dups(uniq))

    L = []
    if first_baseline:
        cnt = {}
        for it in uniq:
            cnt[it["src"]] = cnt.get(it["src"], 0) + 1
        L.append(f"# AI 优惠雷达 · 基线建立（{today.isoformat()}）")
        L.append("")
        L.append(f"已建立基线，监控 **{shelf_count}** 条（跨站合并后）："
                 + "、".join(f"{NAME[k]} {v}" for k, v in cnt.items()))
        L.append("")
        L.append(f"### 当前 {NEAR_DAYS} 天内即将截止（{len(merge_dups(exp_all))} 条）")
        L.append("")
        for it in merge_dups(exp_all):
            tag = "今天" if it["days_left"] == 0 else f"剩 {it['days_left']} 天"
            L.append(f"- {it['title']} — {it['deadline']}（{tag}）")
            if it["link_source"]:
                L.append(f"  来源 {it['link_source']}")
            if it["link_vendor"]:
                L.append(f"  官方 {it['link_vendor']}")
    elif not new_items and not exp_hit and not fresh_events:
        report = ("NO_CHANGE\n\n"
                  f"{today.isoformat()} {now.strftime('%H:%M')} 检查完成："
                  f"在架 {shelf_count} 条，无新增、无新进入 {NEAR_DAYS} 天窗口的活动。\n")
        print(report)
        if UPDATE:
            _save(known, notified, uniq, exp_hit, seen, now, state, report)
        _emit(today, now, new_deals, new_res, exp_all, exp_only, fresh_events, fails,
              shelf_count, False, report, catalog=uniq, raw=records)
        return (10 if not CI else 0)
    else:
        L.append(f"# AI 优惠雷达 · {today.isoformat()}（{now.strftime('%H:%M')}）")
        L.append("")
        if new_deals:
            L.append(f"### 新活动 {len(new_deals)} 条")
            L.append("")
            for it in new_deals:
                dl = f"｜截止 {it['deadline']}" if it["deadline"] else ""
                L.append(f"- {it['title']}{dl}")
                if it["detail"]:
                    L.append(f"  {it['detail'][:150]}")
                if it["link_source"]:
                    L.append(f"  来源 {it['link_source']}")
                if it["link_vendor"]:
                    L.append(f"  官方 {it['link_vendor']}")
                L.append("")
        if exp_only:
            exp_show = merge_dups(exp_only)
            L.append(f"### 即将截止 {len(exp_show)} 条")
            L.append("")
            for it in exp_show:
                tag = "今天截止" if it["days_left"] == 0 else f"剩 {it['days_left']} 天"
                L.append(f"- {it['title']} — {it['deadline']}（{tag}）")
                if it["detail"]:
                    L.append(f"  {it['detail'][:110]}")
                if it["link_source"]:
                    L.append(f"  来源 {it['link_source']}")
                if it["link_vendor"]:
                    L.append(f"  官方 {it['link_vendor']}")
            L.append("")
        if new_res:
            L.append(f"### 新增免费资源 {len(new_res)} 条")
            L.append("")
            for it in new_res:
                L.append(f"- {it['title']}〔{it['cat']}〕")
                if it["detail"]:
                    L.append(f"  {it['detail'][:150]}")
                if it["link_source"]:
                    L.append(f"  来源 {it['link_source']}")
                if it["link_vendor"]:
                    L.append(f"  官方 {it['link_vendor']}")
                L.append("")
        if fresh_events:
            L.append(f"### 免费站状态变化 {len(fresh_events)} 条")
            L.append("")
            for e in fresh_events:
                when = e["at"][:16].replace("T", " ")
                L.append(f"- {when}｜{e['text'][:140]}")
            L.append("")
        if fails:
            L.append("### 来源异常")
            L.append("")
            for sid, why in fails:
                L.append(f"- {NAME.get(sid, sid)}：{why}")
            L.append("")

    report = "\n".join(L) + "\n"
    print(report)

    if UPDATE:
        _save(known, notified, uniq, exp_hit, seen, now, state, report)
    _emit(today, now, new_deals, new_res, exp_all, exp_only, fresh_events,
          fails, shelf_count, True, report, catalog=uniq, raw=records)
    return 0


def _emit(today, now, new_deals, new_res, exp_all, exp_only, events, fails,
          total, has_changes, report, catalog=None, raw=None):
    """流水线三步，每步留产物：

    S1 采集   → docs/stages/01_raw.json     全量原始（含跨源重复、未 key 去重）
    S2 筛选去重 → docs/deals.xml（唯一真源）+ docs/stages/02_active.json
    S3 文案   → docs/brief.txt + docs/stages/03_brief.json（推送端只读这一份）

    界面与推送数据都只从 RSS 派生，避免多处各算一套口径。
    """
    new_keys = {x["key"] for x in new_deals} | {x["key"] for x in new_res}
    notify_keys = {x["key"] for x in exp_only} | new_keys

    # 1) 跨站去重整理：同一活动被多站收录时合成一条，保留全部来源与原始 key
    merged = merge_dups(catalog or [])
    for it in merged:
        keys = it.get("keys") or [it["key"]]
        it["is_new"] = any(k in new_keys for k in keys)
        it["notify"] = any(k in notify_keys for k in keys)
        it["src_name"] = NAME.get(it["src"], it["src"])
        left = None
        if it.get("deadline"):
            try:
                n = (date.fromisoformat(it["deadline"]) - today).days
                left = n if 0 <= n <= NEAR_DAYS else None
            except ValueError:
                left = None
        it["days_left"] = left

    # 2) 写 RSS —— GitHub 每天运行后的最终产物
    rss_io.write_rss(merged, {
        "title": "AI 优惠雷达",
        "site": "https://yutao8.github.io/ai-deal-radar/",
        "description": "AI 厂商限时活动、免费额度与折扣，跨站去重后每日更新",
        "self": "https://raw.githubusercontent.com/yutao8/ai-deal-radar/main/docs/deals.xml",
        "generated_at": now.isoformat(timespec="seconds"),
        "near_days": NEAR_DAYS,
        "built_at": now,
        "has_changes": bool(has_changes),
    }, RSS_PATH)

    # 3) 界面与推送数据从 RSS 派生，统计口径只算这一次
    payload = build_site.from_rss(RSS_PATH)
    payload["events"] = events
    payload["failed_sources"] = [{"source": s, "name": NAME.get(s, s), "reason": w}
                                 for s, w in fails]
    payload["counts"]["failed_sources"] = len(fails)

    # 4) S3 文案：只消费 S2 的结论，推送端一字不改直接发
    brief_text, brief_meta = build_brief.compose(payload)
    payload["brief"] = brief_text
    payload["brief_meta"] = brief_meta
    # 是否值得打扰用户，由这里一次性判定，下游不再二次判断
    payload["should_push"] = bool(has_changes
                                  or payload["counts"].get("new")
                                  or payload["counts"].get("expiring_new"))
    payload["report_md"] = report

    os.makedirs(DOCS, exist_ok=True)
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(CATALOG_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": payload["generated_at"],
            "total": len(merged),
            "items": merged,
        }, f, ensure_ascii=False, indent=1, default=str)
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write(report)
    with open(BRIEF_TXT, "w", encoding="utf-8") as f:
        f.write(brief_text + "\n")

    # 5) 前三步的原始产物各留一份，出问题能逐环节回溯
    os.makedirs(STAGES, exist_ok=True)
    by_src = {}
    for it in (raw or []):
        by_src[it.get("src", "?")] = by_src.get(it.get("src", "?"), 0) + 1
    _dump(os.path.join(STAGES, "01_raw.json"), {
        "stage": 1,
        "title": "采集：七个来源的原始条目，未 key 去重、未跨站合并",
        "generated_at": payload["generated_at"],
        "count": len(raw or []),
        "by_source": {NAME.get(k, k): v for k, v in sorted(by_src.items())},
        "items": raw or [],
    }, compact=True)
    _dump(os.path.join(STAGES, "02_active.json"), {
        "stage": 2,
        "title": "筛选去重：剔除非当前有效条目，跨站同活动合并为一条",
        "generated_at": payload["generated_at"],
        "count": len(merged),
        "split": {"deal": len([x for x in merged if x.get("kind") == "deal"]),
                  "res": len([x for x in merged if x.get("kind") == "res"])},
        "items": merged,
    })
    _dump(os.path.join(STAGES, "03_brief.json"), {
        "stage": 3,
        "title": "文案：手机可读纯文本，推送端直接发送",
        "generated_at": payload["generated_at"],
        "meta": brief_meta,
        "brief": brief_text,
    })


def _dump(path, obj, compact=False):
    kw = ({"separators": (",", ":")} if compact else {"indent": 1})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=str, **kw)


def _save(known, notified, uniq, exp_hit, seen, now, state, report=""):
    today_s = now.date().isoformat()
    for it in uniq:
        known.setdefault(it["key"], today_s)
    for it in exp_hit:
        notified[it["key"]] = it["days_left"]
    for k in list(notified):
        if k not in seen:
            notified.pop(k, None)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({
            "known": known,
            "expiring_notified": notified,
            "last_run": now.isoformat(timespec="seconds"),
            "first_run": state.get("first_run") or now.isoformat(timespec="seconds"),
        }, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
