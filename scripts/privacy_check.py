#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入库前隐私闸门。

两类检查：
  A. 凭证与本机信息：token 前缀、邮箱、手机号、绝对用户路径、本机用户名
  B. 推荐码残留：产物里若仍出现 inviteCode / aff= / ref= 之类参数，直接失败

用法:
    python scripts/privacy_check.py          # 扫描仓库内所有文本文件
    python scripts/privacy_check.py --staged # 只扫 git 暂存区
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".cache"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2",
            ".zip", ".pyc", ".mp4", ".pdf"}

# 允许出现敏感词的文件：清洗规则本身必须写明这些参数名
RULEBOOK = {"scripts/urlkit.py", "scripts/privacy_check.py"}

SECRET_PATTERNS = [
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API key (sk-)"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "Google API key"),
    (re.compile(r"WECOM_CLI_\w+"), "企业微信 CLI 凭证变量"),
    (re.compile(r"user_access_token\s*[=:]"), "企微 access token"),
    (re.compile(r"C:\\\\?Users\\\\?[\w.-]+", re.I), "Windows 用户绝对路径"),
    (re.compile(r"/Users/[\w.-]+/"), "macOS 用户绝对路径"),
    (re.compile(r"\bHBLT\d{3,}\b", re.I), "本机用户名"),
    (re.compile(r"(?<![\w.-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
     "邮箱地址"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
]

REFERRAL_PATTERNS = [
    (re.compile(r"[?&](inviteCode|invite_code|invitation_code)=", re.I), "邀请码参数"),
    (re.compile(r"[?&](aff|aff_id|affiliate_id)=", re.I), "推广分成参数"),
    (re.compile(r"[?&](ref|referral|ref_code)=", re.I), "推荐参数"),
    (re.compile(r"[?&](utm_[a-z]+|spm|scm|coupon|promo_code)=", re.I), "追踪/优惠码参数"),
    (re.compile(r"(?<![a-z])[?&]code=[A-Za-z0-9]{6,}", re.I), "疑似裸推荐码"),
]

# 这些文件是「聚合站的原始来源说明」，允许出现少量追踪参数（不含推荐码）
REFERRAL_SKIP = {"README.md"}


def tracked_files():
    if "--staged" in sys.argv:
        try:
            out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                                 cwd=ROOT, capture_output=True, text=True).stdout
            return [os.path.join(ROOT, p.strip()) for p in out.splitlines() if p.strip()]
        except Exception:
            return []
    files = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            p = os.path.join(base, n)
            if os.path.splitext(n)[1].lower() in SKIP_EXT:
                continue
            if os.path.getsize(p) > 2 * 1024 * 1024:
                continue
            files.append(p)
    return files


def main():
    problems = []
    scanned = 0
    for p in tracked_files():
        if not os.path.isfile(p):
            continue
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        scanned += 1
        for rx, label in SECRET_PATTERNS:
            for m in rx.finditer(text):
                line = text[:m.start()].count("\n") + 1
                problems.append((rel, line, label, m.group(0)[:40]))
        if rel in RULEBOOK or rel in REFERRAL_SKIP:
            continue
        for rx, label in REFERRAL_PATTERNS:
            for m in rx.finditer(text):
                line = text[:m.start()].count("\n") + 1
                problems.append((rel, line, label, m.group(0)[:60]))

    if problems:
        print("✗ 隐私检查未通过，共 %d 处：" % len(problems))
        seen = set()
        for rel, line, label, sample in problems:
            k = (rel, label)
            if k in seen:
                continue
            seen.add(k)
            print(f"  {rel}:{line}  [{label}]  {sample}")
        print("\n请修改后再提交。规则见 scripts/urlkit.py。")
        return 1

    print(f"✓ 隐私检查通过：扫描 {scanned} 个文本文件，未发现凭证、个人信息或推荐码残留。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
