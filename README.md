# Revenue OS

> 小红书运营 AI 副驾驶 — 数据驱动的诊断与增长建议

Revenue OS 把 6,400+ 条小红书官方课程知识与你的真实账号数据深度融合，告诉你**现在最大的问题是什么**，以及**这周该做什么**。

---

## 核心命令

| 命令 | 功能 |
|------|------|
| `/intake` | 填写品牌问卷，生成配置文件（首次使用必做） |
| `/diagnose` | 账号健康评分 + 瓶颈诊断 + KB知识支撑 |
| `/brief` | 本周3个优先执行建议（含优先级排序和预估效果）|

---

## 快速上手

```bash
# 1. 安装
pip install xhs-playbook

# 2. 初始化（约5分钟）
/intake

# 3. 采集账号数据（可选，有更精准的诊断）
opencli xiaohongshu creator-stats -f json > data/creator_stats.json
opencli xiaohongshu creator-notes --limit 50 -f json > data/creator_notes.json

# 4. 诊断
/diagnose

# 5. 获取本周行动计划
/brief
```

---

## 知识库

内置 **6,429 条** Knowledge Objects，来源于小红书官方教育平台课程，覆盖 10 个运营维度：

内容创作 · 流量获取 · 转化路径 · 直播运营 · 数据分析 · 平台规则 · 行业案例 · 选品策略 · 品牌定位 · 账号运营

---

## 数学模型

- **HealthScorer** — 多维指标 → sigmoid 归一化 → 0-100 健康总分
- **SemanticBooster** — BM25 × 指标匹配 × 阶段匹配 × 行业权重（四维乘法）
- **ActionRanker** — Utility × Relevance / Effort^0.5 优先级排序
- **Stabilizer** — Beta-Binomial / Normal-Normal 贝叶斯指标平滑

---

## 数据采集

通过 [opencli](https://github.com/jackwener/opencli) 自动采集创作者数据。部分电商指标（转化率/客单价）需从千帆后台手动填写，详见 [docs/qianfan_guide.md](docs/qianfan_guide.md)。

---

## License

MIT
