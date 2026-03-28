# XHS Playbook

> 小红书创作者和商家的 AI 运营副驾驶 — 数据诊断 × 官方知识 × 增长行动

XHS Playbook 将你的真实账号数据与 **6,400+ 条小红书官方课程知识**深度结合，告诉你现在最大的问题是什么，以及这周该做什么。

知识库来源于小红书官方教育平台（xue.xiaohongshu.com）的课程与直播，涵盖内容创作、流量获取、转化路径、直播运营、数据分析等 10 个维度，经过结构化提取和语义索引，作为每一条建议的依据。

---

## 核心命令

| 命令 | 功能 |
|------|------|
| `/intake` | 填写品牌问卷，生成配置文件（首次必做，约5分钟）|
| `/diagnose` | 账号健康评分 + 瓶颈定位 + 官方课程知识支撑 |
| `/brief` | 本周3个优先执行建议（含优先级排序和预估效果）|

---

## 快速上手

```bash
# 1. 安装
pip install xhs-playbook

# 2. 初始化（约5分钟）
python skills/intake/scripts/intake.py

# 3. 采集账号数据（推荐）
bash scripts/collect_data.sh

# 4. 诊断
python skills/diagnose/scripts/diagnose.py

# 5. 本周行动计划
python skills/brief/scripts/brief.py
```

---

## 知识库

内置 **6,429 条** Knowledge Objects，来源于小红书官方教育平台课程与创作者直播，覆盖 10 个运营维度：

内容创作 · 流量获取 · 转化路径 · 直播运营 · 数据分析 · 平台规则 · 行业案例 · 选品策略 · 品牌定位 · 账号运营

每条知识包含：结论（insight）· 展开解释（detail）· 适用阶段 · 适用行业 · 触发指标。

---

## 数学模型

- **HealthScorer** — 多维指标 → sigmoid 归一化 → 0-100 健康总分
- **SemanticBooster** — BM25 × 指标匹配 × 阶段匹配 × 行业权重（四维乘法）
- **ActionRanker** — Utility × Relevance / Effort^0.5 优先级排序
- **Stabilizer** — Beta-Binomial / Normal-Normal 贝叶斯指标平滑

---

## 数据采集

通过 [opencli](https://github.com/jackwener/opencli) 自动采集创作者数据（曝光/互动/完播率等）。电商转化类指标（进店转化率/客单价）需从千帆后台手动填写，详见 [docs/qianfan_guide.md](docs/qianfan_guide.md)。

---

## License

MIT
