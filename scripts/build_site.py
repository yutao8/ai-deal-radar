#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 RSS 渲染界面。

数据流向固定为：
    check_deals.py 抓取清洗 → docs/deals.xml（唯一真源）
    → build_site.py 读 RSS → docs/index.html + docs/data.json

界面与推送数据都只认 RSS，不再各自持有统计口径。
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
RSS = os.path.join(DOCS, "deals.xml")
sys.path.insert(0, HERE)
import rss_io  # noqa: E402

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#efe9de;font-family:"Microsoft YaHei","PingFang SC",-apple-system,sans-serif;
     color:#221f19;-webkit-font-smoothing:antialiased;padding:28px 16px 60px}
.wrap{max-width:860px;margin:0 auto;background:#fbf8f2;border-radius:18px;overflow:hidden;
      box-shadow:0 10px 40px rgba(30,25,18,.10)}
.head{background:#1b1915;color:#f6f1e7;padding:34px 38px 0}
.kicker{font-size:11px;letter-spacing:.34em;color:#a89f8c;font-weight:700;text-transform:uppercase}
.titlerow{display:flex;align-items:flex-end;justify-content:space-between;margin-top:12px;flex-wrap:wrap;gap:10px}
h1{font-size:42px;font-weight:800;line-height:1;letter-spacing:-.5px}
h1 em{font-style:normal;color:#e8543c}
.stamp{text-align:right;line-height:1.3}
.stamp .d{font-size:22px;font-weight:800}
.stamp .t{font-size:11px;color:#a89f8c;letter-spacing:.14em;margin-top:4px}
.stats{display:flex;margin-top:26px;border-top:1px solid #34302a}
.st{flex:1;padding:16px 0 20px}
.st+.st{border-left:1px solid #34302a;padding-left:24px}
.st b{display:block;font-size:30px;font-weight:800;line-height:1}
.st span{display:block;font-size:11px;color:#a89f8c;margin-top:7px;letter-spacing:.06em}
.st.hot b{color:#f0705a}.st.warn b{color:#e0a94e}.st.cool b{color:#7fb3bd}
.body{padding:30px 38px 6px}
.sec{margin-bottom:28px}
.sechead{display:flex;align-items:center;gap:10px;margin-bottom:4px}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
.sechead h2{font-size:14px;font-weight:800;letter-spacing:.05em;color:#3a352c}
.sechead .range{font-size:11px;color:#9c9384}
.sec.hot .dot{background:#d8422f;box-shadow:0 0 0 4px #f6ddd8}
.sec.warn .dot{background:#c8811a;box-shadow:0 0 0 4px #f5e6cd}
.sec.cool .dot{background:#39707c;box-shadow:0 0 0 4px #d9e7ea}
.item{display:flex;gap:14px;padding:14px 0;border-bottom:1px solid #e9e1d3}
.item:last-child{border-bottom:none}
.it-main{flex:1;min-width:0}
.it-t{font-size:19px;font-weight:700;line-height:1.35;letter-spacing:-.2px}
.it-m{font-size:13px;color:#8b8272;margin-top:6px;line-height:1.55}
.links{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}
.lk{font-size:11.5px;text-decoration:none;padding:4px 10px;border-radius:14px;
    background:#f0e9db;color:#6a6252;border:1px solid #e2d8c6}
.lk.v{background:#1b1915;color:#f6f1e7;border-color:#1b1915}
.lk:hover{opacity:.82}
.tag{flex:none;font-size:11px;font-weight:700;padding:4px 10px;border-radius:20px;height:fit-content;margin-top:3px;white-space:nowrap}
.tag.hot{background:#d8422f;color:#fff}
.tag.warn{background:#f7ead2;color:#a6680c}
.tag.cool{background:#e2edef;color:#2f6069}
.today{background:#fdf3f0;border:1px solid #f2d6cf;border-radius:14px;padding:18px 20px;margin-top:8px}
.today .item{border-bottom:none;padding:8px 0}
.foot{border-top:2px solid #1b1915;margin:6px 38px 0;padding:16px 0 28px;
      display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.foot .l{font-size:12px;color:#6f6757;line-height:1.7}
.foot .r{font-size:11px;color:#a89f8c;letter-spacing:.08em;text-align:right;line-height:1.7}
.foot .r a{color:inherit;text-decoration:none;border-bottom:1px solid #d8cfbd}
.foot .r a:hover{color:#6f6757}
details{margin-top:8px}
summary{cursor:pointer;font-size:13px;font-weight:700;color:#3a352c;padding:10px 0;
        border-top:1px solid #e9e1d3;list-style:none}
summary::-webkit-details-marker{display:none}
summary:before{content:"▸ ";color:#b3a996}
details[open] summary:before{content:"▾ "}
.empty{font-size:13px;color:#9c9384;padding:14px 0}
.warnbox{background:#fdf6e8;border:1px solid #f0dfba;border-radius:12px;padding:14px 16px;
         font-size:12.5px;color:#8a6a1e;margin-bottom:22px;line-height:1.7}
.newsrc{display:inline-block;font-size:11px;color:#8a8175;background:#f0e9db;
        padding:3px 9px;border-radius:12px;margin-top:6px}
@media(max-width:560px){
  body{padding:0}
  .wrap{border-radius:0}
  .head{padding:26px 20px 0}
  .body{padding:22px 20px 4px}
  .foot{margin:6px 20px 0}
  h1{font-size:32px}
  .it-t{font-size:17px}
}
"""


def esc(s):
    return html.escape(str(s or ""), quote=True)


def _days_tag(d):
    if d == 0:
        return '<span class="tag hot">今天</span>'
    if d == 1:
        return '<span class="tag warn">剩 1 天</span>'
    return '<span class="tag cool">剩 %d 天</span>' % d


def _links(it):
    out = []
    if it.get("link_vendor"):
        out.append('<a class="lk v" href="%s" target="_blank" rel="noopener nofollow">厂商原链</a>'
                   % esc(it["link_vendor"]))
    if it.get("link_source"):
        out.append('<a class="lk" href="%s" target="_blank" rel="noopener nofollow">来源 · %s</a>'
                   % (esc(it["link_source"]), esc(it.get("src_name") or "聚合站")))
    return ('<div class="links">%s</div>' % "".join(out)) if out else ""


def _item(it, with_tag=True):
    meta = it.get("detail") or ""
    small = " · ".join(x for x in (it.get("deadline", ""), it.get("cat", "")) if x)
    if small:
        meta = (meta + "　" if meta else "") + small
    return ('<div class="item"><div class="it-main">'
            '<div class="it-t">%s</div><div class="it-m">%s</div>%s</div>%s</div>'
            % (esc(it["title"]), esc(meta), _links(it),
               _days_tag(it["days_left"]) if with_tag and it.get("days_left") is not None else ""))


def build_payload(meta, items):
    """从 RSS 条目派生推送/展示用的口径，只此一处计算。"""
    near = int(meta.get("near_days") or 3)
    expiring = sorted(
        [x for x in items if x.get("days_left") is not None
         and 0 <= x["days_left"] <= near],
        key=lambda x: (x["days_left"], x["title"]))
    new_deals = [x for x in items if x.get("is_new") and x.get("kind") == "deal"]
    new_res = [x for x in items if x.get("is_new") and x.get("kind") == "res"]
    return {
        "schema": 2,
        "source": "docs/deals.xml",
        "generated_at": meta.get("generated_at", ""),
        "generated_date": (meta.get("generated_at") or "")[:10],
        "near_days": near,
        "has_changes": bool(meta.get("has_changes")),
        "counts": {
            "total": len(items),
            "new": len(new_deals) + len(new_res),
            "new_deals": len(new_deals),
            "new_resources": len(new_res),
            "expiring": len(expiring),
            "expiring_new": len([x for x in expiring if x.get("notify")]),
            "failed_sources": 0,
        },
        "new_deals": new_deals,
        "new_resources": new_res,
        "expiring": expiring,
        # 本次需要推送的子集：新活动 + 首次入窗 / 最后一天的到期活动
        "expiring_new": [x for x in expiring if x.get("notify")],
        "events": [],
        "failed_sources": [],
    }


def render(payload):
    d = payload
    c = d["counts"]
    exp = d.get("expiring") or []
    new_deals = d.get("new_deals") or []
    new_res = d.get("new_resources") or []
    fails = d.get("failed_sources") or []
    date_s = d.get("generated_date") or ""
    time_s = (d.get("generated_at") or "")[11:16]

    today_items = [x for x in exp if x.get("days_left") == 0]
    soon1 = [x for x in exp if x.get("days_left") == 1]
    soon2 = [x for x in exp if x.get("days_left", 9) >= 2]

    parts = ['<div class="head"><div class="kicker">Daily Deal Radar</div>'
             '<div class="titlerow"><h1>AI 优惠<em>雷达</em></h1>'
             '<div class="stamp"><div class="d">%s</div><div class="t">%s 更新</div></div></div>'
             '<div class="stats">'
             '<div class="st hot"><b>%d</b><span>今天截止</span></div>'
             '<div class="st warn"><b>%d</b><span>剩 1 天</span></div>'
             '<div class="st cool"><b>%d</b><span>剩 2 天以上</span></div>'
             '</div></div>'
             % (esc(date_s[5:].replace("-", "·")), esc(time_s),
                len(today_items), len(soon1), len(soon2))]

    body = []
    if fails:
        body.append('<div class="warnbox">⚠ %d 个来源本次异常，结果可能不完整：%s</div>'
                    % (len(fails), esc("、".join(f.get("name", "") for f in fails))))

    body.append('<div class="sec hot"><div class="sechead"><span class="dot"></span>'
                '<h2>今天截止</h2><span class="range">%s</span></div>' % esc(date_s))
    if today_items:
        body.append('<div class="today">%s</div>'
                    % "".join(_item(x, with_tag=False) for x in today_items))
    else:
        body.append('<div class="empty">今天没有到期的活动。</div>')
    body.append('</div>')

    for label, group in (("剩 1 天", soon1), ("剩 2 天以上", soon2)):
        if not group:
            continue
        body.append('<div class="sec warn"><div class="sechead"><span class="dot"></span>'
                    '<h2>%s</h2><span class="range">%d 条</span></div>'
                    % (label, len(group)))
        body.append("".join(_item(x) for x in group))
        body.append('</div>')

    if new_deals or new_res:
        body.append('<div class="sec cool"><div class="sechead"><span class="dot"></span>'
                    '<h2>本次新增</h2><span class="range">%d 条</span></div>'
                    % (len(new_deals) + len(new_res)))
        body.append("".join(_item(x) for x in (new_deals + new_res)))
        body.append('</div>')

    body.append('<details><summary>关于数据源（%d 条在架）</summary>' % c["total"])
    body.append('<div class="empty">本页由 <b>deals.xml</b> 渲染而成：GitHub Actions 每天抓取七个来源，'
                '跨站去重后写成 RSS，界面与推送数据都从该 RSS 派生。'
                '所有链接已剥离推荐码与追踪参数。</div>')
    body.append('</details>')

    parts.append('<div class="body">%s</div>' % "".join(body))
    parts.append('<div class="foot"><div class="l">在架 %d 条 · 近 %d 天到期 %d 条 · 本次新增 %d 条<br>'
                 '源数据 deals.xml ｜ 全部链接已去推荐码</div>'
                 '<div class="r">%s<br><a href="deals.xml">RSS</a> · '
                 '<a href="data.json">data.json</a> · '
                 '<a href="poster.html">分页预览</a></div></div>'
                 % (c["total"], d.get("near_days", 3), c["expiring"], c["new"],
                    esc(d.get("generated_at", ""))))

    doc = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<title>AI 优惠雷达 · %s</title>'
           '<link rel="alternate" type="application/rss+xml" title="AI 优惠雷达" href="deals.xml">'
           '<style>%s</style></head><body><div class="wrap">%s</div></body></html>'
           % (esc(date_s), CSS, "".join(parts)))

    os.makedirs(DOCS, exist_ok=True)
    out = os.path.join(DOCS, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    return out


def from_rss(path=RSS):
    """读 RSS → payload，并渲染界面。"""
    meta, items = rss_io.read_rss(path)
    payload = build_payload(meta, items)
    render(payload)
    return payload


if __name__ == "__main__":
    p = from_rss()
    print("docs/index.html 已由 deals.xml 渲染，在架 %d 条" % p["counts"]["total"])
