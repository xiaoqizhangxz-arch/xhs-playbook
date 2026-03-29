# XHS 数据采集指南
> Revenue OS 运营数据采集规范  更新：2026-03-28

---

## 架构说明

```
脚本负责（稳定、可cron）          Agent 负责（需判断、Vision）
─────────────────────────         ─────────────────────────────
Creator API 数据                  Canvas 图表 OCR
千帆 DOM 文本数据（表格类）        采集异常恢复
每日/周/月定时触发                 首次全量（引导人工确认）
指标结构化解析                     snapshot 质量核验
用户分析页每日快照（18+视图）      笔记详情月流量分析
```

---

## 页面清单（完整）

### A. 千帆数据页 `/app-datacenter/*`（有日期筛选，按月采集）

| 页面 | 路径 | 数据内容 | 日期筛选 |
|------|------|---------|---------|
| 成交分析 | /business-overview | GMV、订单、CVR、载体/账号/人群构成 | ✅ |
| 流量数据 | /flow-overview | 访客、曝光、点击率 | ✅ |
| 商品总览 | /good-data | SKU级销售 | ✅ |
| 搜索总览 | /search-overview | 搜索曝光/点击 | ✅ |
| 引流搜索词 | /search-overview/words | Top关键词 | ✅ |
| 账号分析 | /business-account | 账号成交贡献 | ✅ |
| 笔记数据 | /note-data/goods | 笔记带货成交 | ✅ |
| 店铺主页 | /homepage | 主页进店转化 | ✅ |
| 评价数据 | /comment-overview | 评分、评价数 | ✅ |
| 订单明细 | /business-order | 逐笔订单 | ✅ |
| 物流数据 | /logistics-data | 发货/签收时效 | ✅ |
| 客服数据 | /customer-data | 咨询量、响应率 | ✅（周粒度）|
| 群聊数据 | /group-chat | 群聊成交 | ✅ |

> ⚠️ **日历选择器限制**：只能在同一面板内两次点击选日期（不能跨面板/翻页），详见 `docs/qianfan_calendar_automation.md`

### B. 人群分层页 `/app-circle/user-data`（每日快照，无日期筛选）

**脚本**：`acquisition/collect_user_pages.mjs`

6个主Tab × 3个子Tab = **18个视图**

| 主Tab | 子Tab | 关键数据 |
|-------|-------|---------|
| 认知/意向/新客/老客/流失/粉丝 | 人群流转 | 流转图（Canvas，需OCR） |
| 同上 | 用户画像 | 性别、年龄、省份TOP10、活跃时段 |
| 同上 | 用户数据 | 近7/30天：访客、浏览、下单/支付买家、GMV、客单价 |

### C. AINRL漏斗页 `/app-promotion/user-assets`（每日快照，无日期筛选）

**脚本**：`acquisition/collect_user_pages.mjs`

5个主Tab × 2个子Tab + 笔记详情

| 主Tab | 子Tab | 关键数据 |
|-------|-------|---------|
| 了解(A)/新客(N)/老客(R)/亲密(L) | 用户数据 | 人群变化趋势、关注/加群/加购/成交 |
| 同上 | 用户画像 | 性别/年龄/地理/九大人群 |
| 兴趣(I) | 用户数据 | **含兴趣行为明细**（阅读/浏览/收藏行为） + 各笔记感兴趣人数 |
| 兴趣(I) | 用户画像 | 兴趣点偏好、品牌舆情偏好 |

> ℹ️ **兴趣行为明细**不是独立第三个tab，而是兴趣(I)→用户数据的下半部分，采集用户数据时自动包含。

**笔记详情**：兴趣行为明细里每条笔记有"更多信息"链接，点击跳转：
```
/app-datacenter/note-detail?id={noteId}&type=seller&dateType={...}
```
每篇笔记包含近一月流量分析（按感兴趣人数排序，自动去重采集）。

---

## 一、首次全量采集（人工执行一次）

### 前提检查
```bash
opencli doctor          # 确认 Extension Connected
# Chrome 确认已登录：
#   creator.xiaohongshu.com（Default Profile）
#   ark.xiaohongshu.com（Default Profile，注意不是 Profile 1）
# Chrome 已开启：查看→开发者→允许 Apple 事件中的 JavaScript
```

### 执行千帆数据页
```bash
cd "Revenue OS 路径"
PYTHONPATH=scripts python3 -m revenue_os.acquisition.xhs_historical_collector \
  --start 2026-01-01 --end 2026-03-31
```

### 执行用户分析页（每日快照）
```bash
node scripts/revenue_os/acquisition/collect_user_pages.mjs --date=2026-03-28
```

---

## 二、常规监控节奏

### 每日（自动，cron 07:30）
```bash
# 千帆数据页（当月）
PYTHONPATH=scripts python3 -m revenue_os.acquisition.xhs_full_collector --mode daily

# 用户分析页快照（18个分层视图 + AINRL + 笔记详情）
node scripts/revenue_os/acquisition/collect_user_pages.mjs
```

### 每周一 08:00
```bash
PYTHONPATH=scripts python3 -m revenue_os.acquisition.xhs_full_collector --mode weekly
```

### 每月1日 09:00
```bash
PYTHONPATH=scripts python3 -m revenue_os.acquisition.xhs_full_collector --mode monthly
```

---

## 三、Canvas 图表 OCR 标准流程（Agent 执行）

人群流转图 + 用户画像图均为 Canvas，文本采集只能拿到数字，图形部分需 Agent OCR。

```python
# 采集逻辑
canvas_raw = node _daemon_exec.mjs canvas {tab_id}
# → 返回 JSON: {"canvas_0": {"w":972, "h":600, "data":"data:image/png;base64,..."}, ...}

# 保存 PNG
for key, val in canvas_data.items():
    if val["data"].startswith("data:image"):
        save_png(val["data"], path=f"canvas_images/{date}_{page}_{key}.png")

# Vision 提取
image_tool(path, prompt="提取所有图表数值，以JSON输出")
```

---

## 四、数据质量核验清单

```
□ 人群分层：18个文件均存在且 > 300 chars
□ AINRL：10个文件均存在（5tab × 2subtab）
□ 兴趣(I)用户数据：contains "感兴趣人数" 且 > 1000 chars
□ 笔记详情：无重复 noteId
□ 千帆数据页：成交分析含"支付转化率"
□ Canvas 图表：如月度，audience_profile 字段存在
```

---

## 五、Cron 配置

```bash
# 每日 07:30 千帆
30 7 * * * cd /path/to/revenue-os && PYTHONPATH=scripts python3 -m revenue_os.acquisition.xhs_full_collector --mode daily >> logs/daily_collect.log 2>&1

# 每日 08:00 用户分析页快照
0 8 * * * cd /path/to/revenue-os && node scripts/revenue_os/acquisition/collect_user_pages.mjs >> logs/user_pages.log 2>&1

# 每周一 08:30
30 8 * * 1 cd /path/to/revenue-os && PYTHONPATH=scripts python3 -m revenue_os.acquisition.xhs_full_collector --mode weekly >> logs/weekly_collect.log 2>&1

# 每月1日 09:00
0 9 1 * * cd /path/to/revenue-os && PYTHONPATH=scripts python3 -m revenue_os.acquisition.xhs_full_collector --mode monthly >> logs/monthly_collect.log 2>&1
```

---

## 六、故障处理

| 症状 | 原因 | 解决 |
|------|------|------|
| `ECONNREFUSED 19825` | opencli daemon 挂了 | `opencli doctor` 重连 |
| ark 页面 < 200 chars | session 丢失或 navigate 跑了新窗口 | 手动打开 ark tab，点 Connected，重跑 |
| canvas 全为空 `{}` | 图表未渲染完 | 增加等待时间（8s→15s） |
| creator API `code=-1` | 签名缺失 | 确认 tab 在 creator/new/home，从该页面发 fetch |
| Apple 事件 JS 报错 | 权限未开启 | Chrome→查看→开发者→允许 Apple 事件中的 JS |
| 用户分析页 757 chars 不变 | automation tab 在后台，Vue 暂停渲染 | AppleScript 激活 tab 后重跑 |
| 日历跨月失败 | 千帆日历选择器限制 | 见 qianfan_calendar_automation.md |

---

## 七、文件命名规范

```
# 千帆数据页（按月段）
{YYYY-MM-DD}_{YYYY-MM-DD}_{页面名}.txt
例：2026-01-01_2026-01-31_成交分析.txt

# 人群分层快照
{YYYY-MM-DD}_人群分层_{主Tab}_{子Tab}.txt
例：2026-03-28_人群分层_认知_用户画像.txt

# AINRL快照
{YYYY-MM-DD}_AINRL_{主Tab}_{子Tab}.txt
例：2026-03-28_AINRL_兴趣(I)_用户数据.txt

# 笔记详情
{YYYY-MM-DD}_笔记详情_{noteId}.txt
例：2026-03-28_笔记详情_69896d120000000015030070.txt

# 人群分析概览快照
{YYYY-MM-DD}_snapshot_人群分析.txt
```
