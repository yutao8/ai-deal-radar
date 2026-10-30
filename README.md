# AI 优惠雷达

每天自动巡检 AI 厂商的限时活动、免费额度与折扣，编译成结构化数据与静态页，供外部读取并推送。

- 静态页：<https://yutao8.github.io/ai-deal-radar/>
- 数据契约：<https://raw.githubusercontent.com/yutao8/ai-deal-radar/main/docs/data.json>

## 它做什么

每天 07:00（北京时间）由 GitHub Actions 跑一次采集，把结果写回仓库：

| 文件 | 用途 |
| --- | --- |
| `docs/data.json` | **对外契约**。当天需要推送的内容，字段见下 |
| `docs/catalog.json` | 全部在架条目（290 条左右），供站内检索 |
| `docs/index.html` | 自包含静态页，无 JS 依赖，手机可直接看 |
| `docs/latest.md` | 当天变动报告（Markdown 原文） |
| `data/state.json` | 基线：哪些条目已知、哪些已提醒过。跨天去重靠它 |

> 为什么把基线提交进仓库：Actions 的 runner 是一次性的，基线只能靠仓库持久化，否则每天都会把「全部条目」当成新增重推一遍。

## 两类链接（重点）

每条活动输出两个链接，语义不同，别混用：

- **`link_source`（来源链接）**：这条活动是在哪个聚合站被发现的，指向该站的信息页。
  例：`https://aitkradar.cn/deals/manual-qoder-intl-communityboost/`
- **`link_vendor`（厂商原链）**：厂商自己的活动页 / 产品页 / 官方文档。
  例：`https://docs.qoder.com/events/communityboost.md`

抓取时的取字段规则：

| 来源 | `link_source` | `link_vendor` |
| --- | --- | --- |
| S1 aitkradar RSS | `<link>` 条目页 | `依据：` 后的官方文档地址 |
| S2 apiprice JSON-LD | `itemListElement.url`（带锚点） | `item.url` 官方定价页 |
| S3 devtk 卡片 | 站点页 | 卡片内 CTA 按钮链接，其次 nofollow 依据链接 |
| S4 ai-coding-welfare | GitHub 仓库 | `homeUrl`（优先）或 `signupUrl` |
| S5 FreeLLM-API-KeyHub | GitHub 仓库 | 小节内首个外部链接 |
| S6 Token FBI | `token-fbi.com/table/` | `entry_url` / `intel_url` |
| S7 TokenTab | `tokentab.cn/deals.html` | 条目 `url` |

## 推荐码与追踪参数

`scripts/urlkit.py` 在输出前统一清洗：

1. **查询参数**：命中 `utm_*`、`ref`、`aff`、`inviteCode`、`spm`、`coupon`、`code` 等一律删除。
2. **推荐路径**：`/invite`、`/aff`、`/referral`、`/share` 等段落直接截断。
   例如 `https://www.codebuddy.cn/events/invite?inviteCode=<已隐去>`
   → `https://www.codebuddy.cn/events/`
3. **分享按钮**：`twitter.com/intent`、`facebook.com/sharer` 之类不算落地页，直接丢弃。

这套规则由 `scripts/privacy_check.py` 在 CI 里强制校验，产物中一旦出现推荐码参数，构建直接失败。

## 数据契约

`docs/data.json`：

```jsonc
{
  "schema": 2,
  "generated_at": "2026-10-30T14:29:00+08:00",
  "generated_date": "2026-10-30",
  "near_days": 3,
  "has_changes": true,          // 当天是否有需要推送的变化
  "should_push": true,          // S3 的最终判定：是否值得打扰用户
  "counts": {
    "total": 258,               // 在架总数（跨站合并后）
    "new": 0,                   // 新增（活动 + 免费资源）
    "expiring": 14,             // 3 天内到期，全部
    "expiring_new": 0,          // 其中本次需要提醒的
    "failed_sources": 0
  },
  "new_deals": [Item],
  "new_resources": [Item],
  "expiring": [Item],           // 窗口内全部，供展示
  "expiring_new": [Item],       // 需要提醒的子集，供推送判定
  "events": [{ "at": "", "text": "" }],
  "failed_sources": [{ "source": "", "name": "", "reason": "" }],
  "brief": "【AI 优惠雷达】10-30 14:33\n\n■ 新活动\n...",  // S3 成品文案，推送端原样发送
  "brief_meta": { "chars": 994, "dropped": 0, "items": 13, "limit": 1500 },
  "report_md": "## 当天报告原文"
}
```

`Item`：

```jsonc
{
  "title": "Qoder 国际站 Community Boost",
  "detail": "阶梯加赠最高 4,096 SOTA Credits",
  "cat": "赠送额度",
  "deadline": "2026-10-30",
  "days_left": 0,               // 仅到期条目有
  "src": "aitkradar",
  "src_name": "AI价格雷达",
  "srcs": ["aitkradar", "tokentab"],
  "link_source": "https://aitkradar.cn/deals/...",
  "link_vendor": "https://docs.qoder.com/events/communityboost.md"
}
```

## 流水线：三步，每步留产物

判断全部在这三步里做完，下游只消费最后一步的 `brief`。

| 阶段 | 脚本 | 产物 | 条数口径 |
|------|------|------|----------|
| S1 采集 | `check_deals.py`（七源解析 + 链接清洗） | `docs/stages/01_raw.json` | 290（含跨源重复） |
| S2 筛选去重 | `check_deals.py`（`merge_dups`） | `docs/deals.xml`（唯一真源）、`docs/stages/02_active.json` | 258（当前有效，合并后） |
| S3 文案 | `build_brief.py`（`compose`） | `docs/brief.txt`、`docs/stages/03_brief.json`、`data.json` 的 `brief` | 推送条目数 |

- **为什么每一步都留一份**：S1 记录「到底抓到了什么」，解析器被网站改版打挂时能直接对比；S2 记录合并结果，跨站去重规则调整后能看出哪几条被并；S3 记录实际发出的文本，同一份 `generated_at` 可复现。
- **口径只在一处算**：`docs/deals.xml` 是唯一真源，`data.json`、`index.html`、`brief` 全部从它派生，所以 `counts.total` 与报告里的「在架」必然一致。
- **文案的截断优先级**：今天截止 → 剩 1 天 → 其它新条目 → 剩 2 天以上；超 1500 字时从后往前牺牲，末尾标注「另有 N 条略」。
- **下游不做判断**：推送端只读 `should_push` 与 `brief`，拿不到 `brief` 就报错停下，不会在本地重拼一份。

## 分页预览（截图用）

`docs/poster.html` 把当日结论切成固定尺寸的页面，专门用来截图发图文或短视频。三套模板，尺寸严格等于画布，浏览器缩放到 100% 截下来就是成品：

| 模板 | 画布 | 每页条数 | 适用 |
|---|---|---|---|
| `xhs` | 1080 × 1440（3:4） | 4 | 小红书图文 |
| `dy` | 1080 × 1920（9:16） | 4 | 抖音 / 视频号竖屏 |
| `list` | 1080 × 1440（3:4） | 5 | 小红书清单风、公众号头图 |

用法（URL 参数）：

```
poster.html?tpl=xhs&p=1            预览第 1 页（带底部工具栏，可点着翻）
poster.html?tpl=dy&p=2&clean=1     截图模式：隐藏工具栏、不缩放，页面即画布
poster.html?tpl=list&all=1         竖向堆叠全部页，用来整体扫一眼
```

- 页序固定为：封面（含「今日速览」三条）→ 条目页 → 尾页；页头标签按本页内容取（今天截止 / 48 小时内截止 / 三天内截止），不写模板名。
- 条目优先级：今天截止 → 剩 1 天 → 新增 → 其余窗口内；总量超过 9 页时截断，尾页注明「另有 N 条」。
- 图片里只放厂商域名，不放完整链接——图文平台对正文外链不友好，链接适合放在评论区或简介。
- 标题最多两行，用 CSS `line-clamp` 截断，不预先砍字符，避免出现「SOTA C…」这种断词。
- 键盘 `←` `→` 翻页，页码显示在工具栏右侧；页面内容全部服务端渲染，不依赖 JS 拼装。

## 提醒口径

- **新活动**：基线里不存在 → 立即提醒。
- **即将截止**：3 天内到期。进入窗口时提醒一次，最后一天（`days_left == 0`）再提醒一次，中间天数不重复。
- 以上状态记在 `data/state.json` 的 `expiring_notified` 里，格式是 `key -> 上次提醒时的剩余天数`。

## 本地运行

```bash
python scripts/check_deals.py              # 正常跑，无变化返回 10
python scripts/check_deals.py --ci         # CI 模式，恒返回 0
python scripts/check_deals.py --no-update  # 只看结果，不改基线
python scripts/privacy_check.py            # 隐私闸门
python scripts/build_site.py               # 单独重渲染静态页
python scripts/build_brief.py              # 单独重出推送文案（读 docs/data.json）
python scripts/poster.py                   # 单独重出分页预览（读 docs/data.json）
```

依赖：Python 3.9+（仅标准库）、Node 18+（S7 的数据源是 UMD 模块，需要 node 求值）。

## 隐私

仓库里**只**有抓取代码、活动数据与基线。不含：个人身份信息、企业微信凭证、本机路径、推送目标。
`scripts/privacy_check.py` 检查 token 前缀、邮箱、手机号、Windows/macOS 用户目录绝对路径、本机用户名，
以及产物里的推荐码残留；任何一项命中，CI 直接失败。

推送环节（企业微信）完全在本机进行，不经过 Actions，也就不需要往仓库放任何 secret。
