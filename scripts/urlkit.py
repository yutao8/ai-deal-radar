#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""链接清洗与厂商原链识别。

两条规则：
  1. 去掉一切推广/追踪参数（utm_*、ref、aff、inviteCode、spm…），
     路径里若含 /invite、/aff、/referral 之类推荐路径，一并截断。
  2. 区分两类链接：
     - link_source：这条活动是在哪个聚合站被发现的（来源链接，指向信息页）
     - link_vendor：厂商自己的官方页面（原链接，指向活动说明或产品页）
"""
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# 聚合站：出现在这些域名下的链接都算「来源」，不能当厂商原链
AGGREGATOR_HOSTS = {
    "aitkradar.cn",
    "apiprice.app",
    "devtk.ai",
    "token-fbi.com",
    "tokentab.cn",
    "github.com",
    "raw.githubusercontent.com",
}

# 纯追踪参数（整词匹配，小写比较）
TRACK_PARAMS = {
    "ref", "ref_", "refer", "referer", "referrer", "referral", "referral_code",
    "referralcode", "ref_code", "refcode", "refid", "ref_id", "rid",
    "aff", "aff_id", "affid", "affcode", "aff_code", "affiliate",
    "affiliate_id", "affiliateid", "afftrack", "partner", "partner_id",
    "invite", "invite_code", "invitecode", "invite_code_id", "inviteid",
    "inviter", "inviter_code", "invitercode", "invitation", "invitation_code",
    "icode", "rcode", "share", "share_code", "sharecode", "share_id", "shareid",
    "promo", "promo_code", "promocode", "promo_id", "promoid",
    "coupon", "coupon_code", "couponcode", "voucher", "discount",
    "discount_code", "discountcode", "code", "redeem", "redeemcode",
    "from", "from_source", "fromsource", "source", "src", "channel",
    "spm", "scm", "track", "tracking", "tracking_id", "trackid", "trk",
    "click", "click_id", "clickid", "cid", "campaign", "campaign_id",
    "gclid", "fbclid", "yclid", "msclkid", "ttclid", "twclid", "dclid",
    "_hsenc", "_hsmi", "mkt_tok", "mc_cid", "mc_eid", "vero_id", "vero_conv",
    "bd_vid", "hmsr", "hmpl", "hmcu", "hmkw", "hmci", "sa", "sc",
}

# 前缀型追踪参数
TRACK_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_", "ga_", "wt_", "oly_")

# 推荐/邀请专用路径：命中即截断
REFERRAL_PATH_RE = re.compile(
    r"/(invite|invitation|inviter|referral|refer|aff|affiliate|partner|share)"
    r"(?:/|$)", re.I)

# 分享按钮这类链接不是厂商落地页
SHARE_HOST_RE = re.compile(
    r"(twitter\.com/intent|facebook\.com/sharer|x\.com/intent|linkedin\.com/share"
    r"|weibo\.com/share|t\.me/share|api\.whatsapp\.com/send)", re.I)


def host_of(url):
    try:
        h = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def is_aggregator(url):
    h = host_of(url)
    if not h:
        return True
    return any(h == a or h.endswith("." + a) for a in AGGREGATOR_HOSTS)


def sanitize_url(url, drop_fragment=False):
    """去掉推广参数与推荐路径；无法解析时原样返回（去空白）。"""
    if not url:
        return ""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        return ""
    if SHARE_HOST_RE.search(url):
        return ""
    try:
        sp = urlsplit(url)
    except ValueError:
        return ""

    # 1) 查询串过滤
    keep = []
    for k, v in parse_qsl(sp.query, keep_blank_values=True):
        kl = k.lower()
        if kl in TRACK_PARAMS:
            continue
        if any(kl.startswith(p) for p in TRACK_PREFIXES):
            continue
        keep.append((k, v))
    query = urlencode(keep, doseq=True)

    # 2) 路径里的推荐段截断：/events/invite -> /events
    path = sp.path or "/"
    m = REFERRAL_PATH_RE.search(path)
    if m:
        cut = path[:m.start()]
        path = cut if cut and cut != "/" else "/"
        # 截断后若原参数只为推荐服务，已在上一步清掉，这里无需再处理
        if not path.endswith("/") and cut and cut != "/":
            path = path + "/"

    frag = "" if drop_fragment else sp.fragment
    out = urlunsplit((sp.scheme.lower(), sp.netloc.lower(), path, query, frag))
    return out.rstrip("?&")


def pick_vendor(urls, extra_deny=()):
    """从候选里挑出第一个「厂商域名」链接，已清洗。"""
    deny = tuple(extra_deny)
    for u in urls:
        if not u:
            continue
        u = u.strip()
        if not re.match(r"^https?://", u, re.I):
            continue
        if SHARE_HOST_RE.search(u):
            continue
        h = host_of(u)
        if not h:
            continue
        if any(h == d or h.endswith("." + d) for d in deny):
            continue
        if is_aggregator(u):
            continue
        clean = sanitize_url(u)
        if clean:
            return clean
    return ""


def pick_source(url, fallback=""):
    """来源链接：优先聚合站信息页，其次兜底页。"""
    for u in (url, fallback):
        c = sanitize_url(u or "")
        if c:
            return c
    return ""


def pair_links(source_candidates, vendor_candidates, source_fallback=""):
    """返回 (link_source, link_vendor)。"""
    ls = ""
    for u in source_candidates:
        if u and is_aggregator(u):
            ls = pick_source(u)
            if ls:
                break
    if not ls:
        ls = pick_source(source_fallback)
    lv = pick_vendor(vendor_candidates)
    if lv and ls and lv.split("#")[0] == ls.split("#")[0]:
        lv = ""
    return ls, lv
