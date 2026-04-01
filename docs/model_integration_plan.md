# Revenue OS Model Integration Plan (Revenue OS only)

日期：2026-04-01
范围：`~/code/revenue-os`（不含 Le Fond Bridge 外部脚本）

---

## 1) 现有模型全景（接入状态）

| 模型 | 文件 | 状态 | 主要输入 | 主要输出 | 断路原因 |
|---|---|---|---|---|---|
| HealthScorer | `revenue_os/modeling/health_scorer.py` | **未接入主链路**（定义完成） | `user_state.metrics` + benchmark | `total_score` / `dimension_scores` / `bottleneck` | 未被 CLI / planner 调用（仅定义函数） |
| Stabilizer | `revenue_os/modeling/stabilizer.py` | **已接入** | metric_registry 原始指标（numerator/denominator） | `estimated_value`, `ci80/95`, `prob_above_target` 等 | 无（已在 `build_metric_registry` 内调用） |
| ExperimentBayes | `revenue_os/modeling/experiment_bayes.py` | **已接入**（execution score） | `metric_deltas`, `guardrail_deltas`, completion, sample_sufficiency | `outcome`, `evidence_cap`, posterior summary | end_state 缺失或指标名错配时，`primary_delta=None`，结论长期 E0/E1 |
| Calibration | `revenue_os/modeling/calibration.py` | **stub** | 无 | 仅 `CALIBRATION_VERSION` 与 `calibration_ref()` | 没有真实校准参数、没有训练/回写流程 |
| Baselines | `revenue_os/modeling/baselines.py` | **旁路使用**（eval/replay） | `state.metric_snapshot` | mission baseline 选择 | 不参与在线 planner 决策 |
| PostFeedback | `revenue_os/modeling/post_feedback.py` | **已接入** | first_party content + creator rows + metric_map | `post_feedback_report` | 依赖 creator 数据新鲜度，非阻塞 |
| ConversionDoctor | `revenue_os/specialists/conversion_doctor.py` | **已接入** | current_state | conversion actions | 动作模板静态（弱个性化） |
| Repurchase specialist | `revenue_os/specialists/repurchase.py` | **已接入** | current_state | repurchase actions | 同上（静态模板） |
| SearchPositioning specialist | `revenue_os/specialists/search_positioning.py` | **已接入** | `search_opportunities` | search actions | 依赖 search 输入质量 |
| ActionRanker | `revenue_os/planning/action_ranker.py` | **未接入主链路**（定义完成） | KO + user_state + bottleneck | priority_score 排序 | `packages.py` 还在用 specialist 固定优先级 |
| SemanticBooster | `revenue_os/retrieval/semantic_booster.py` | **半接入** | KO + user_state + bottleneck | 4维 boost 分数 | `packages.py` 调 `retrieve_for_mission()` 未传 `user_state`，boost未生效 |
| KBRetriever | `revenue_os/knowledge/kb_retriever.py` | **已接入** | mission_type + bottleneck | `kb_insights`（top-k） | 目前主要 BM25；semantic boost 未完全启用 |

---

## 2) xlsx_etl → 现有模型的数据流断点

`xlsx_etl.run_etl()` 产出结构：
- `metrics`: `monthly_gmv`, `monthly_orders`, `aov`, `shop_visit_to_pay_cvr`, `visitors`, `refund_rate`
- `ainrl.derived`: `a_to_i`, `i_to_n`, `n_to_r`, `r_to_l`
- `top_search_terms`: `term`, `clicks`, `ctr`, `revenue`, `purchase_cvr`
- `transaction_history` / `refund_history`

当前主链路消费的是 `current_state.metric_snapshot`（来自 `registry/metrics.py`），字段集合更大且命名不同。

### 2.1 字段名不匹配（etl vs 模型期望）

| ETL字段 | 主链路/模型期望 | 状态 |
|---|---|---|
| `metrics.shop_visit_to_pay_cvr` | `shop_visit_to_pay_cvr` | 直接可映射 |
| `metrics.aov` | `aov` | 直接可映射 |
| `metrics.refund_rate` | `refund_rate` | 直接可映射 |
| `ainrl.derived.i_to_n` | `deal_intent_to_new_cvr` / `aipl_interest_to_new_cvr` | **需转换**（语义接近但不是同口径） |
| `ainrl.derived.n_to_r` | `repurchase_rate` / `deal_new_to_returning_cvr` | **需转换** |
| `top_search_terms[*].ctr` | `search_ctr` | **需聚合**（median/weighted mean） |
| `top_search_terms[*].purchase_cvr` | `search_purchase_cvr` | **需聚合** |
| `metrics.monthly_gmv` | 当前无同名核心 metric（更多在 monthly_health 域） | **缺失映射层** |

### 2.2 缺少字段（ETL无法直接喂给现有模型）

- `product_click_to_pay_cvr`
- `inquiry_to_pay_cvr`
- creator 侧核心字段：`creator_cover_ctr_7d`, `creator_completion_rate_7d`, `recent_note_median_views`, `recent_note_count_30d`
- deal/aipl 细颗粒人群流转字段（registry 中 `deal_*` / `aipl_*`）

### 2.3 需要新增的转换层代码（建议）

1. `revenue_os/normalization/xlsx_state_adapter.py`（新文件）
   - `etl_to_metric_registry_like(etl_snapshot: dict) -> dict[str, Any]`
   - 产出可并入 `state.metric_snapshot` 的最小字段集

2. `revenue_os/state/current_state.py`
   - 新增 `merge_etl_metric_snapshot(state: dict, etl_snapshot: dict) -> dict`
   - 将 ETL 指标写入 `state.metric_snapshot`，并打 `source_truth="xlsx_history_truth"`

3. `revenue_os/execution/experiments.py`
   - `_metric_delta(...)` 改为“多源取值”：先 `metric_snapshot`，缺失则从 `state.etl_metrics` 取

---

## 3) 实验闭环断路修复（Sprint 2 重点）

### 3.1 当前断路点

`execution/experiments.py::_metric_delta()` 仅比较：
- `start_state.metric_snapshot[metric]`
- `end_state.metric_snapshot[metric]`

当 end_state 不存在、或 metric 名不在 snapshot（尤其 ETL 新增字段）时，`primary_delta=None`，Bayes端只能输出保守结论（倾向 inconclusive / E0~E1）。

### 3.2 具体修复方案（最小改动）

#### A. 统一 delta 计算口径
新增函数（同文件）：
- `_lookup_metric_value(state, metric_name)`
  - 先看 `state.metric_snapshot`
  - 再看 `state.etl_metrics` 映射（如 `ainrl_i_to_n_cvr -> deal_intent_to_new_cvr`）

#### B. delta 公式
- 比率类：`delta = end - start`
- 金额类（如 aov）：`delta = end - start`
- 可选附加：`relative_delta = (end-start)/max(start, eps)`（用于报告，不替代现有 Bayes 输入）

#### C. 修改位置
- 文件：`revenue_os/execution/experiments.py`
- 函数：`_metric_delta`, `score_experiment`
- 改动量：约 **20-35 行** 可落地

---

## 4) KB triggering_metrics ↔ xlsx_etl 精确映射

基于 `kb_retriever.MISSION_QUERY_MAP` + KO 常见 triggering metrics，对齐 ETL：

| KB triggering_metric | xlsx_etl 对应字段 | 映射状态 |
|---|---|---|
| `shop_visit_to_pay_cvr` | `metrics.shop_visit_to_pay_cvr` | 直接 |
| `aov` | `metrics.aov` | 直接 |
| `refund_rate` | `metrics.refund_rate` | 直接 |
| `search_ctr` | `top_search_terms[*].ctr` 聚合 | 需转换 |
| `search_purchase_cvr` | `top_search_terms[*].purchase_cvr` 聚合 | 需转换 |
| `repurchase_rate` | `ainrl.derived.n_to_r`（代理） | 需转换（口径差） |
| `deal_intent_to_new_cvr` | `ainrl.derived.i_to_n`（代理） | 需转换（口径差） |
| `product_click_to_pay_cvr` | 无 | 缺失 |
| `inquiry_to_pay_cvr` | 无 | 缺失 |

### 自动链路建议

`metrics_snapshot(etl)` -> `adapter` -> `current_state.metric_snapshot` -> `mission_plan` -> `packages.kb_insights`

并在 `packages.py` 调用改为：
```python
retrieve_for_mission(
    mission_type,
    bottleneck=state.get("primary_bottleneck"),
    user_state={
      "stage": state.get("stage"),
      "industry": state.get("brand_context", {}).get("industry", "通用"),
      "business_model": state.get("brand_context", {}).get("business_model", []),
      "weak_metrics": [...],
    },
    top_k=5,
)
```
这样 `semantic_booster` 的 stage/industry/weak_metric 才真正启用。

---

## 5) 开源化关键设计决策（非路径层硬编码）

### 5.1 当前业务硬编码点

1. `state/current_state.py`
   - `mtd_partial_month` 用 `"03月"` 结尾判断（Le Fond 时段特化）
2. `analysis_rules.md`
   - 大量 Le Fond / 银饰阈值与文案（非通用）
3. specialist 文案
   - action title/diagnosis 偏珠宝语义，参数化不足
4. `semantic_booster.SIMILAR_INDUSTRIES`
   - 行业图谱静态写死，覆盖不完整

### 5.2 参数化建议

- 新建 `revenue_os/config/domain_profiles/*.yaml`
  - `industry_thresholds`
  - `seasonality`
  - `metric_aliases`
  - `action_copy_templates`
- `analysis_rules.md` 拆为模板 + profile 注入
- `current_state` 中去掉月份硬编码，改为 `is_partial_month(latest_month, now)`

---

## 6) 3个 Sprint（按 ROI）

### Sprint 1（本周，最高ROI）— 打通 ETL 到在线决策

1. **接入 ETL 适配层**
   - 文件：`normalization/xlsx_state_adapter.py`（新）
   - 函数：`etl_to_metric_registry_like` / `merge_into_state_snapshot`
   - 效果：256个历史 xlsx 进入主链路，不再只做离线报告

2. **让 KB 检索吃到 user_state（激活 semantic boost）**
   - 文件：`execution/packages.py`
   - 函数：`generate_execution_package`
   - 效果：`kb_insights` 从“关键词命中”升级为“阶段/行业/瓶颈个性化命中”

3. **补齐 search 聚合指标**
   - 文件：`xlsx_etl.py`
   - 函数：新增 `derive_search_metrics()`
   - 效果：`search_ctr/search_purchase_cvr` 可直接驱动 search mission

### Sprint 2（下周）— 修复实验闭环（E0问题）

1. **实验 delta 多源取值**
   - 文件：`execution/experiments.py`
   - 函数：`_metric_delta`, `_lookup_metric_value`（新增）
   - 效果：end_state 可算出真实 delta，evidence_class 不再长期卡 E0

2. **增加窗口对齐规则**
   - 文件：`execution/experiments.py`
   - 函数：`_latest_state_after`
   - 效果：避免拿到“同窗口重复快照”导致 delta≈0 的伪中性

3. **experiment_result 增加 relative_delta**
   - 文件：`execution/experiments.py`
   - 效果：便于治理层判断“统计显著但商业幅度不足”

### Sprint 3（下下周）— 校准与开源通用化

1. **把 calibration 从 stub 升级为可读参数**
   - 文件：`modeling/calibration.py` + `config/calibration/*.yaml`
   - 效果：stabilizer/experiment_bayes 共享可维护先验

2. **domain profile 参数化**
   - 文件：`config/domain_profiles/*.yaml`, `analysis_rules.md` 生成逻辑
   - 效果：不同行业可复用同一引擎

3. **接入 ActionRanker 到 package 生成**
   - 文件：`execution/packages.py`, `planning/action_ranker.py`
   - 效果：由固定 priority 变为 Utility×Relevance/Effort 的动态排序

---

## 结论（短版）

- Revenue OS 的复杂模型**不是没有**，而是存在“已实现但未串联”的问题：`HealthScorer/ActionRanker/SemanticBooster` 都是典型半接入。
- 真正的第一优先不是再写新模型，而是把 `xlsx_etl` 指标接到 `current_state/experiments`，否则实验闭环一直会偏 E0。
- 本周做完 Sprint 1，系统就会从“有模型”升级为“模型能吃到你今天采集的256份历史数据并驱动动作”。
