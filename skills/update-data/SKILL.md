# /update-data — 全量数据更新

## 描述
采集所有数据源的最新数据，智能识别增量，去重后写入 source_auto/。
完成后通知用户采集报告（哪些 covered，哪些还不行）。

## 触发
用户输入 `/update-data`

## 时间窗口逻辑
- 默认：从上次成功采集时间到现在
- 首次运行：最近 30 天
- 支持手动指定：`/update-data --from 2026-01-01 --to 2026-03-28`

## 数据源分层

### 层1: Creator API（快速，无需浏览器）
- `opencli xiaohongshu creator-stats`   → 账号总览/涨粉趋势
- `opencli xiaohongshu creator-notes`   → 全量笔记列表
- `opencli xiaohongshu creator-profile` → 账号信息

### 层2: Creator Browser Context（playwright + Chrome cookie）
- `creator_home`         → 首页 KPI 面板 + 趋势图 PDF
- `creator_note_manager` → 全量笔记（无限滚动，目标114+条）
- `creator_stats_overview` → 观看来源分布 (canvas → PDF → OCR)
- `creator_stats_fans`     → 粉丝画像/趋势 (canvas → PDF → OCR)
- `creator_stats_content`  → 帖子详细数据 (canvas → PDF → OCR)

### 层3: 千帆 ARK DOM（browser bridge）
- `xhs_historical_collector.py` → 23个数据页的文字数据

### 层4: 千帆 ARK XLSX（browser bridge，点击下载）
- `download_xlsx.mjs` → 14个页面 XLSX（成交/流量/商品/搜索/笔记/账号/退款/订单/评价）
- 时间窗口：设置到与层3一致

### 层5: 用户分析快照（browser bridge）
- `collect_user_pages.mjs` → 人群分层×18 + AINRL×10 + 笔记详情

## 运行方式
后台执行（可能30-60分钟），完成后推送通知

## 用法
```bash
python skills/update-data/scripts/update_data.py
python skills/update-data/scripts/update_data.py --from 2026-01-01 --to 2026-03-28
python skills/update-data/scripts/update_data.py --layer creator  # 只跑 creator
python skills/update-data/scripts/update_data.py --layer ark      # 只跑千帆
python skills/update-data/scripts/update_data.py --dry-run        # 只看缺口不采集
```

## 输出
- 终端/通知：采集报告（coverage summary）
- `runtime/last_update.json`：本次运行结果
- `runtime/update_manifest.json`：历史运行记录（用于时间窗口计算）
