# Revenue OS 架构概览
> 更新：2026-03-28

---

## 项目定位

Revenue OS 是 LE FOND 小红书店铺的数据采集+分析+执行系统，目标是将所有运营数据系统化采集、结构化存储，为 Scout 模型（转化优化）和 Brand Intelligence（内容决策）提供数据基础。

---

## 代码库结构

```
xhs-playbook/                      # GitHub: xiaoqizhangxz-arch/xhs-playbook
├── revenue_os/
│   ├── acquisition/               # 数据采集层（核心）
│   │   ├── canvas_ocr.py          # creator canvas 图表 → PDF → OCR
│   │   ├── collect_user_pages.mjs # 人群分层+AINRL 用户快照
│   │   ├── creator_capture.py     # playwright creator 页面采集
│   │   ├── creator_catalog.py     # creator surfaces 定义
│   │   ├── download_xlsx.mjs      # 千帆14页面 XLSX 自动下载
│   │   ├── xhs_full_collector.py  # 千帆 ARK DOM 采集（单次快照）
│   │   ├── xhs_historical_collector.py  # 千帆 ARK 历史采集（带日期）
│   │   └── ...（采集基础设施）
│   ├── foundation/                # 配置/路径/ID/IO 工具
│   ├── ingest/                    # 数据解析入库
│   ├── modeling/                  # 指标稳定化/预测
│   ├── registry/                  # 指标/实体注册表
│   ├── planning/                  # 执行方案生成
│   ├── evaluation/                # Codex 评估
│   └── cli.py                     # 命令行入口
├── skills/
│   ├── update-data/               # /update-data 全量更新 skill
│   │   ├── SKILL.md
│   │   └── scripts/update_data.py
│   ├── diagnose/                  # /diagnose 账号健康诊断
│   ├── brief/                     # /brief 本周执行简报
│   └── intake/                    # /intake 数据导入
├── docs/
│   ├── XHS_DATA_COLLECTION_GUIDE.md  # 采集详细规范（主文档）
│   └── revenue_os_architecture_overview.md  # 本文件
└── runtime/                       # 运行时状态
    ├── update_manifest.json       # /update-data 时间戳记录
    └── last_update.json           # 最近一次运行结果
```

---

## 数据采集分层

### Layer 1: Creator API（opencli，最快）
- **工具**: `opencli xiaohongshu creator-*`
- **时间**: 实时，无需设置
- **数据**: 账号指标趋势/全量笔记列表/单篇详情

### Layer 2a: Creator Browser（playwright）
- **工具**: `creator_capture.py`
- **时间**: 页面默认（近7天）
- **数据**: 首页 KPI 面板 + 全量笔记列表（无限滚动，114+条）

### Layer 2b: Canvas OCR
- **工具**: `canvas_ocr.py`
- **时间**: 近7天 / 近30天 tab（平台限制，无自定义）
- **数据**: 账号概览趋势图 / 粉丝画像（性别/年龄/城市/兴趣）
- **OCR**: Gemini 2.0 Flash（主力）→ Claude Haiku（fallback）

### Layer 3: 千帆 ARK DOM
- **工具**: `xhs_historical_collector.py`
- **时间**: `--start/--end` 任意日期范围，自动分段（≤90天/段）
- **数据**: 23个数据页全量文字数据

### Layer 4: 千帆 XLSX
- **工具**: `download_xlsx.mjs`
- **时间**: ⚠️ 当前为页面默认窗口（待实现日期设置）
- **数据**: 14个页面报表下载，自动存入 `source_auto/`

### Layer 5: 用户快照
- **工具**: `collect_user_pages.mjs`
- **时间**: 当日快照（无时间窗口）
- **数据**: 人群分层×18 + AINRL×11 + 笔记详情×10

---

## Slash Commands

| 命令 | 说明 | 运行方式 |
|------|------|---------|
| `/update-data` | 全量数据更新（5层，增量，后台） | `python skills/update-data/scripts/update_data.py` |
| `/diagnose` | 账号健康诊断（读取已采集数据） | `python skills/diagnose/scripts/diagnose.py` |
| `/brief` | 本周执行建议（基于诊断+KB） | `python skills/brief/scripts/brief.py` |
| `/intake` | 手动数据导入 | `python skills/intake/scripts/intake.py` |

---

## 数据流

```
原始采集 → raw_data/creator_auto/ (JSON/PDF)
         → raw_data/source_auto/  (XLSX)
         → raw_data/creator_auto/historical/ (TXT)

解析入库 → revenue_os ingest → extracted/ (结构化 JSON)

分析输出 → analysis/ (BL cards / Scout metrics)
         → runtime/ (当前状态 / 实验记录)
```

---

## 待解决障碍

| 障碍 | 优先级 | 说明 |
|------|--------|------|
| XLSX 日期范围设置 | 中 | download_xlsx.mjs 需在下载前设置时间 tab |
| 千帆日历跨月 | 低 | set_ark_date_range 需补充月份导航逻辑 |
| Creator stats 自定义日期 | 无需 | 平台本身只提供近7/30天，非脚本限制 |

---

## 环境变量

| 变量 | 用途 | 是否必须 |
|------|------|---------|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Canvas OCR 主力模型 | 强烈推荐 |
| `ANTHROPIC_API_KEY` | Claude Haiku fallback | 可选 |
| `REVENUE_OS_BASE_DIR` | 覆盖 iCloud 路径 | 可选 |
| `REVENUE_OS_PLAYWRIGHT_CHANNEL` | playwright 浏览器 channel | 可选 |

---

## iCloud 同步路径

```
~/Library/Mobile Documents/com~apple~CloudDocs/
└── Thoth_Academy_Obsidian/
    └── 08_Le_Fond_Bridge/
        └── Business Library/
            └── raw_data/         ← Revenue OS 数据根目录
                ├── creator_auto/
                ├── source_auto/
                ├── source/       (手动历史)
                ├── users/        (手动历史)
                └── pdfs/         (手动历史)
```
