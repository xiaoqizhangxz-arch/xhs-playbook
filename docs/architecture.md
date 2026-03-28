# Revenue OS 系统架构

```
/intake → brand_profile.yaml
    ↓
collect_data.sh → data/*.json (via opencli)
    ↓
state_normalizer.py → user_state (metrics + weak_metrics)
    ↓
health_scorer.py → total_score + bottleneck
    ↓
kb_retriever.py (BM25 × SemanticBooster) → top-K KOs
    ↓
action_ranker.py (Utility × Relevance / Effort^0.5) → ranked actions
    ↓
/diagnose → 健康报告    /brief → 执行简报
```

## 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 品牌配置 | `normalization/profile_builder.py` | 问卷→brand_profile，冷启动先验 |
| 数据标准化 | `normalization/state_normalizer.py` | opencli JSON → user_state |
| 健康评分 | `modeling/health_scorer.py` | sigmoid归一化→5维度→0-100总分 |
| 指标稳定 | `modeling/stabilizer.py` | Beta-Binomial/Normal-Normal贝叶斯平滑 |
| KB检索 | `knowledge/kb_retriever.py` | BM25 + SemanticBooster四维乘法 |
| 语义增强 | `retrieval/semantic_booster.py` | metrics/stage/bm/industry权重 |
| 行动排序 | `planning/action_ranker.py` | Utility-Effort优先级 |
