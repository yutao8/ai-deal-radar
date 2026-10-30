#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分页预览（poster）—— 把当日结论切成固定尺寸页面，用于截图发图文/视频。

产物：docs/poster.html
用法：
    docs/poster.html?tpl=xhs&p=1&clean=1    # 小红书 3:4，第 1 页，无工具栏（截图用）
    docs/poster.html?tpl=dy&p=2&clean=1     # 抖音 9:16
    docs/poster.html?tpl=list&all=1         # 清单风，竖向堆叠全部页

设计约束（为了截图能直接用）：
- 每页尺寸严格等于模板尺寸，body 无边距，clean=1 时不缩放、不显示工具栏
- 内容全部服务端渲染好，不依赖 JS 拼装，无头浏览器打开即定稿
- 图片里只放厂商域名，不放完整链接（小红书/抖音对正文内的外链不友好）
"""
import html
import json
import os
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
DATA_JSON = os.path.join(DOCS, "data.json")
OUT = os.path.join(DOCS, "poster.html")

TEMPLATES = {
    "xhs": {"w": 1080, "h": 1440, "per": 4, "name": "小红书 · 3:4"},
    "dy": {"w": 1080, "h": 1920, "per": 4, "name": "抖音 · 9:16"},
    "list": {"w": 1080, "h": 1440, "per": 5, "name": "清单 · 3:4"},
}

MAX_PAGES = 9  # 超过这个页数没人看完，宁可在尾页说「另有 N 条」

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:#e8e6e1}
body{font-family:"Microsoft YaHei","PingFang SC",-apple-system,sans-serif;color:#221f19;
     --w:1080px;--h:1440px;--pad:78px;--ink:#221f19;--sub:#8b8272;--line:#e6ddcd;
     --bg:#fbf8f2;--card:#fff;--hot:#d8422f;--warn:#c8811a;--cool:#39707c;--kick:#a89f8c}
body.tpl-dy{--h:1920px;--pad:88px;--bg:#0d0d10;--ink:#f7f7f5;--sub:#8d8d93;--line:#24242b;
     --card:#15151a;--hot:#ff5f4d;--warn:#ffc247;--cool:#2ee6a8;--kick:#5c5c66}
body.tpl-list{--pad:72px;--bg:#ffffff;--ink:#141414;--sub:#7a7a7a;--line:#e8e8e8;
     --card:#fafafa;--hot:#e0342a;--warn:#b8741a;--cool:#2f6a76;--kick:#9b9b9b}

#stage{display:flex;flex-direction:column;align-items:center;gap:34px;padding:34px 0 60px}
body.clean #stage{padding:0;gap:0}
body.all #stage{gap:26px}

.pg{width:var(--w);height:var(--h);background:var(--bg);color:var(--ink);
    position:relative;overflow:hidden;display:none;flex-direction:column;
    padding:var(--pad);transform-origin:top center}
.pg.on{display:flex}
body.all .pg{display:flex}

/* ---------- 封面 ---------- */
.cv{justify-content:space-between}
.cv .top{display:flex;justify-content:space-between;align-items:baseline;
         font-size:22px;letter-spacing:.42em;color:var(--kick);font-weight:700;text-transform:uppercase}
.cv .mid{margin-top:auto;margin-bottom:36px}
.cv h1{font-family:"Songti SC","SimSun",Georgia,serif;font-size:150px;line-height:1.02;
       font-weight:800;letter-spacing:-4px}
.cv h1 em{font-style:normal;color:var(--hot)}
.cv .sub{margin-top:34px;font-size:38px;line-height:1.5;color:var(--sub);max-width:820px}
.cv .rule{height:3px;background:var(--ink);margin:44px 0 40px;opacity:.9}
.cv .nums{display:flex;gap:0}
.cv .n{flex:1}
.cv .n+.n{border-left:1px solid var(--line);padding-left:44px}
.cv .n b{display:block;font-size:74px;font-weight:800;line-height:1;letter-spacing:-2px}
.cv .n span{display:block;font-size:23px;color:var(--sub);margin-top:14px;letter-spacing:.08em}
.cv .n.h b{color:var(--hot)}.cv .n.w b{color:var(--warn)}.cv .n.c b{color:var(--cool)}
.cv .bot{display:flex;justify-content:space-between;align-items:flex-end;
         font-size:24px;color:var(--sub);letter-spacing:.04em}
/* 封面下方的「今日速览」，填掉留白并给出信息钩子 */
.peek{border-top:1px solid var(--line);padding-top:30px}
.peek .ph{font-size:22px;letter-spacing:.3em;color:var(--kick);font-weight:700;margin-bottom:8px}
.peek .pi{display:flex;gap:20px;align-items:baseline;padding:18px 0;
          border-bottom:1px solid var(--line)}
.peek .pi:last-child{border-bottom:none}
.peek .pk{font-size:24px;color:var(--hot);font-weight:800;flex:none;width:64px}
.peek .pt{font-size:31px;font-weight:700;line-height:1.35;flex:1;min-width:0;
          display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.peek .pd{font-size:23px;color:var(--sub);flex:none}

/* ---------- 条目页 ---------- */
.phead{display:flex;justify-content:space-between;align-items:center;
       padding-bottom:26px;border-bottom:3px solid var(--ink)}
.phead .l{font-size:34px;font-weight:800;letter-spacing:.06em}
.phead .r{font-size:24px;color:var(--kick);letter-spacing:.16em;font-variant-numeric:tabular-nums}
.list{margin-top:10px;flex:1;display:flex;flex-direction:column;justify-content:center}
.row{display:flex;gap:30px;padding:40px 0;border-bottom:1px solid var(--line);
     align-items:flex-start}
.row:last-child{border-bottom:none}
.idx{flex:none;width:96px;font-family:"Songti SC","SimSun",Georgia,serif;font-size:52px;
     font-weight:800;color:var(--kick);line-height:1.1;letter-spacing:-1px}
.rmain{flex:1;min-width:0}
.rt{font-size:46px;font-weight:800;line-height:1.3;letter-spacing:-.6px;
    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rmeta{margin-top:14px;font-size:26px;color:var(--sub);line-height:1.5}
.rmeta .v{color:var(--ink);font-weight:700}
.pill{display:inline-block;font-size:23px;font-weight:800;padding:7px 20px;border-radius:30px;
      margin-bottom:16px;letter-spacing:.04em}
.pill.p0{background:var(--hot);color:#fff}
.pill.p1{background:var(--warn);color:#231a08}
.pill.p2{background:transparent;color:var(--cool);border:2px solid var(--cool)}
.pfoot{display:flex;justify-content:space-between;align-items:center;
       padding-top:24px;border-top:1px solid var(--line);font-size:23px;color:var(--kick);
       letter-spacing:.1em;font-variant-numeric:tabular-nums}

/* ---------- 尾页 ---------- */
.end{justify-content:center}
.end .big{font-family:"Songti SC","SimSun",Georgia,serif;font-size:96px;font-weight:800;
          line-height:1.2;letter-spacing:-2px}
.end .big em{font-style:normal;color:var(--hot)}
.end p{margin-top:40px;font-size:30px;line-height:1.85;color:var(--sub);max-width:820px}
.end .src{margin-top:56px;padding-top:34px;border-top:3px solid var(--ink);font-size:25px;
          color:var(--sub);line-height:2}
.end .src b{color:var(--ink)}
.note{margin-top:34px;font-size:24px;color:var(--hot);font-weight:700;line-height:1.6}

/* ---------- 清单模板的紧凑排版 ---------- */
body.tpl-list .pg{padding:var(--pad) var(--pad) 56px}
body.tpl-list .phead{border-bottom:none;background:#141414;color:#fff;
     margin:calc(var(--pad) * -1) calc(var(--pad) * -1) 0;padding:44px var(--pad) 40px}
body.tpl-list .phead .r{color:#9b9b9b}
body.tpl-list .row{padding:26px 0}
body.tpl-list .rt{font-size:36px}
body.tpl-list .idx{width:74px;font-size:38px;font-family:inherit;color:#c9c9c9}
body.tpl-list .rmeta{font-size:22px;margin-top:10px}
body.tpl-list .pill{font-size:20px;padding:5px 16px;margin-bottom:12px}
body.tpl-list .cv h1{font-size:120px}
body.tpl-list .cv .sub{font-size:32px}
body.tpl-list .peek .pt{font-size:29px}

/* ---------- 深色模板的对比度 ---------- */
body.tpl-dy .row{padding:44px 0}
body.tpl-dy .rt{font-size:56px}
body.tpl-dy .rmeta{font-size:30px}
body.tpl-dy .idx{font-size:62px;width:110px}
body.tpl-dy .pill{font-size:26px;padding:9px 24px}
body.tpl-dy .phead .l{font-size:38px}
body.tpl-dy .cv h1{font-size:172px}
body.tpl-dy .cv .sub{font-size:42px}
body.tpl-dy .cv .n b{font-size:84px}
body.tpl-dy .cv .n span{font-size:26px}
body.tpl-dy .peek .pt{font-size:33px}
body.tpl-dy .cv .rule{background:var(--cool);opacity:1}

/* ---------- 预览用工具栏（clean=1 时彻底隐藏） ---------- */
#bar{position:fixed;left:0;right:0;bottom:0;background:#1b1915;color:#e9e4d8;
     display:flex;gap:14px;align-items:center;padding:12px 20px;font-size:13px;
     font-family:"Microsoft YaHei",sans-serif;z-index:99;flex-wrap:wrap}
#bar b{color:#f0c05a}
#bar a,#bar button{background:#2f2b25;color:#e9e4d8;border:1px solid #46403a;
     border-radius:8px;padding:7px 13px;font-size:13px;cursor:pointer;text-decoration:none;
     font-family:inherit}
#bar .sp{flex:1}
#bar code{background:#0f0e0c;padding:6px 10px;border-radius:6px;color:#a8d8a0;font-size:12px}
body.clean #bar{display:none}
body.clean .pg{transform:none!important}
body.clean #stage{padding:0}
"""

JS = """
(function(){
  var q=new URLSearchParams(location.search);
  var tpl=q.get('tpl')||'xhs';
  var clean=q.get('clean')==='1';
  var all=q.get('all')==='1';
  var p=parseInt(q.get('p')||'1',10);
  document.body.className='tpl-'+tpl+(clean?' clean':'')+(all?' all':'');
  var pgs=[].slice.call(document.querySelectorAll('.pg'));
  var mine=pgs.filter(function(el){return el.dataset.tpl===tpl});
  pgs.forEach(function(el){el.classList.remove('on')});
  if(all){mine.forEach(function(el){el.classList.add('on')});}
  else{
    if(isNaN(p)||p<1)p=1;
    if(p>mine.length)p=mine.length;
    if(mine[p-1])mine[p-1].classList.add('on');
    if(!clean){
      var hud=document.getElementById('hud');
      if(hud)hud.textContent=p+' / '+mine.length;
    }
  }
  if(!clean){
    var fit=function(){
      var pg=document.querySelector('.pg.on');
      if(!pg)return;
      var s=Math.min(1,(window.innerHeight-150)/pg.offsetHeight,(window.innerWidth-60)/pg.offsetWidth);
      document.querySelectorAll('.pg').forEach(function(el){el.style.transform='scale('+s+')'});
    };
    fit();window.addEventListener('resize',fit);
  }
  document.addEventListener('keydown',function(e){
    if(all)return;
    var np=p;
    if(e.key==='ArrowRight')np=p+1;
    if(e.key==='ArrowLeft')np=p-1;
    if(np!==p){
      q.set('p',np);q.set('tpl',tpl);
      location.search=q.toString();
    }
  });
})();
"""


def esc(s):
    return html.escape(str(s or ""), quote=True)


def host(item):
    u = (item.get("link_vendor") or item.get("link_source") or "").strip()
    if not u:
        return ""
    try:
        h = urlparse(u).netloc
    except ValueError:
        h = ""
    return h[4:] if h.startswith("www.") else h


def clip(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _tier(item):
    d = item.get("days_left")
    if d is None:
        return 2
    if d <= 0:
        return 0
    if d == 1:
        return 1
    return 2


def collect_items(payload):
    """选出适合上图的条目：今天截止 → 剩 1 天 → 新增/其余窗口内，去重。"""
    buckets = {0: [], 1: [], 2: []}
    seen = set()
    for it in (payload.get("expiring") or []):
        k = it.get("key") or it.get("title")
        if k in seen:
            continue
        seen.add(k)
        buckets[_tier(it)].append(it)
    extra = []
    for it in (payload.get("new_deals") or []) + (payload.get("new_resources") or []):
        k = it.get("key") or it.get("title")
        if k in seen:
            continue
        seen.add(k)
        extra.append(it)
    items = buckets[0] + buckets[1] + extra + buckets[2]
    return items


def build_pages(payload, per, total_pages_cap=MAX_PAGES):
    """封面 + 条目页 + 尾页。返回 (pages, omitted)。"""
    items = collect_items(payload)
    room = (total_pages_cap - 2) * per
    omitted = max(0, len(items) - room)
    shown = items[:room]

    pages = [{"kind": "cover"}]
    for i in range(0, max(len(shown), 1), per):
        chunk = shown[i:i + per]
        if not chunk:
            break
        pages.append({"kind": "items", "items": chunk, "start": i})
    pages.append({"kind": "end", "omitted": omitted})
    return pages, omitted


def _deadline_short(it):
    d = it.get("days_left")
    if d is None:
        return "长期"
    if d <= 0:
        return "今天"
    return "剩 %d 天" % d


def page_label(items):
    """页头标签按本页内容取，不写模板名——图片是给读者看的。"""
    ds = [it.get("days_left") for it in items]
    known = [d for d in ds if d is not None]
    if any(d == 0 for d in known):
        return "今天截止"
    if any(d == 1 for d in known):
        return "48 小时内截止"
    if known:
        return "三天内截止"
    return "值得一看"


def render_cover(payload, meta, peek_items):
    c = payload.get("counts") or {}
    date_s = payload.get("generated_date") or ""
    exp = payload.get("expiring") or []
    n0 = len([x for x in exp if x.get("days_left") == 0])
    n1 = len([x for x in exp if x.get("days_left") == 1])
    n2 = len([x for x in exp if (x.get("days_left") or 0) >= 2])
    d = date_s[5:].replace("-", " / ") if date_s else ""

    peek = []
    for it in peek_items:
        peek.append(
            '<div class="pi"><span class="pk">%s</span>'
            '<span class="pt">%s</span><span class="pd">%s</span></div>'
            % (esc(_deadline_short(it)), esc(it.get("title") or ""), esc(host(it)))
        )

    return (
        '<section class="pg cv" data-tpl="%s">'
        '<div class="top"><span>AI DEAL RADAR</span><span>%s</span></div>'
        '<div class="mid">'
        '<h1>AI 优惠<em>雷达</em></h1>'
        '<div class="sub">今天截止 <b>%d</b> 个、两天内 <b>%d</b> 个。<br>'
        '免费额度与限时折扣，挑还来得及的看。</div>'
        '<div class="rule"></div>'
        '<div class="nums">'
        '<div class="n h"><b>%d</b><span>今天截止</span></div>'
        '<div class="n w"><b>%d</b><span>剩 1 天</span></div>'
        '<div class="n c"><b>%d</b><span>剩 2 天以上</span></div>'
        '</div></div>'
        '<div class="peek"><div class="ph">今日速览</div>%s</div>'
        '<div class="bot"><span>在架 %d 条 · 每日更新</span><span>%s</span></div>'
        '</section>'
        % (meta["tpl"], esc(d), n0, n0 + n1, n0, n1, n2,
           "".join(peek), c.get("total", 0), esc(meta["site"]))
    )


def render_items(page, meta, page_no, page_total, label):
    rows = []
    for i, it in enumerate(page["items"]):
        idx = page["start"] + i + 1
        d = it.get("days_left")
        if d is None:
            pill = '<span class="pill p2">长期有效</span>'
        elif d <= 0:
            pill = '<span class="pill p0">今天截止</span>'
        elif d == 1:
            pill = '<span class="pill p1">剩 1 天</span>'
        else:
            pill = '<span class="pill p2">剩 %d 天</span>' % d
        h = host(it)
        bits = [x for x in (esc(it.get("cat") or ""), esc(h)) if x]
        rows.append(
            '<div class="row"><div class="idx">%02d</div><div class="rmain">'
            '%s<div class="rt">%s</div>'
            '<div class="rmeta">%s</div></div></div>'
            % (idx, pill, esc(it.get("title") or ""),
               ' · '.join('<span class="v">%s</span>' % b if k == 1 else b
                          for k, b in enumerate(bits)))
        )
    return (
        '<section class="pg" data-tpl="%s">'
        '<div class="phead"><span class="l">%s</span><span class="r">%02d / %02d</span></div>'
        '<div class="list">%s</div>'
        '<div class="pfoot"><span>AI 优惠雷达</span><span>%s</span></div>'
        '</section>'
        % (meta["tpl"], esc(label), page_no, page_total,
           "".join(rows), esc(meta["date_short"]))
    )


def render_end(page, meta):
    note = ""
    if page.get("omitted"):
        note = '<div class="note">另有 %d 条未上图，完整清单见站点</div>' % page["omitted"]
    return (
        '<section class="pg end" data-tpl="%s">'
        '<div class="big">每天 <em>07:00</em><br>自动更新</div>'
        '<p>七个来源抓取，跨站去重后才上榜。<br>'
        '链接里的推荐码与追踪参数全部剥掉，点进去就是厂商原页。</p>'
        '%s'
        '<div class="src"><b>数据源</b>　AI价格雷达 / apiprice / DevTk / Token FBI / '
        'TokenTab / ai-coding-welfare / FreeLLM-API-KeyHub<br>'
        '<b>站点</b>　%s<br><b>快照</b>　%s</div>'
        '</section>'
        % (meta["tpl"], note, esc(meta["site"]), esc(meta["generated_at"]))
    )


def render(payload):
    date_s = payload.get("generated_date") or ""
    meta_base = {
        "site": "yutao8.github.io/ai-deal-radar",
        "date_short": date_s,
        "generated_at": payload.get("generated_at") or "",
    }
    sections = []
    peek_items = collect_items(payload)[:3]
    for tpl, cfg in TEMPLATES.items():
        pages, omitted = build_pages(payload, cfg["per"])
        total = len(pages)
        for i, pg in enumerate(pages, start=1):
            meta = dict(meta_base, tpl=tpl, section=cfg["name"])
            if pg["kind"] == "cover":
                sections.append(render_cover(payload, meta, peek_items))
            elif pg["kind"] == "items":
                sections.append(render_items(pg, meta, i, total, page_label(pg["items"])))
            else:
                sections.append(render_end(pg, meta))

    bar = (
        '<div id="bar">'
        '<b>分页预览</b>'
        '<a href="?tpl=xhs&p=1">小红书</a>'
        '<a href="?tpl=dy&p=1">抖音</a>'
        '<a href="?tpl=list&p=1">清单</a>'
        '<a href="?tpl=xhs&all=1">全部页</a>'
        '<span class="sp"></span>'
        '<span>页码 <span id="hud">1 / 1</span></span>'
        '<code>← → 翻页</code>'
        '<a href="?tpl=xhs&p=1&clean=1">进入截图模式</a>'
        '</div>'
    )

    doc = (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>AI 优惠雷达 · 分页预览</title><style>%s</style></head><body>'
        '<div id="stage">%s</div>%s<script>%s</script></body></html>'
        % (CSS, "".join(sections), bar, JS)
    )

    os.makedirs(DOCS, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    return OUT


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DATA_JSON
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    out = render(payload)
    counts = payload.get("counts") or {}
    pages = sum(len(build_pages(payload, c["per"])[0]) for c in TEMPLATES.values())
    print("%s 已生成：三套模板共 %d 页，在架 %s 条" % (out, pages, counts.get("total", "?")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
