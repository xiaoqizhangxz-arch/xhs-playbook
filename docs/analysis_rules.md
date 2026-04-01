# Revenue OS — 数据分析规则 v1.0

> 生成日期：2026-04-01
> 适用阶段：ramp_up（月GMV ¥21K）
> 行业：珠宝配饰 / 银饰 DTC

---

## Task A：各数据类型分析规则

### A1. GMV / 转化率时序分析

**KB依据**：
- dimension=`data_analytics`, triggering_metrics=`shop_visit_to_pay_cvr`
- 「破冰期后的经营逻辑跃迁」：GMV达2万以上才算真正破冰，之后从分散测试转向验证复制。来源：消费品新锐成长营 (unit__2a59b825)
- 「小红书种草具备成长性与长效ROI」：首月ROI较低，半年后稳步增长至2.5-3。来源：消费品新锐成长营 (unit__2a59b825)

**分析方向**：
1. MoM 增长率是否加速（加速=连续2月MoM>15%）
2. GMV构成：笔记直购 vs 搜索成交 vs 直播成交比例变化
3. 转化率趋势：进店→支付转化率是否随流量增长而稀释

**健康阈值**（ramp_up阶段）：

| 指标 | 好 | 警告 | 差 | 来源 |
|------|------|------|------|------|
| 月GMV MoM增长率 | >30% | 10-30% | <10%或负增长 | 专业推断（ramp_up阶段应高速增长） |
| 进店-支付转化率 | >3% | 2-3% | <2% | KB: DEFAULT_THRESHOLDS + 珠宝行业调整 |
| 客单价 | >¥200 | ¥100-200 | <¥100 | KB: aov_low=300 但 Le Fond ¥199主力SKU，调整为¥200 |

**触发动作**：
- GMV MoM<10% → mission: `content_formula_scaling`（内容公式放量）
- 转化率<2% → mission: `conversion_repair`（商品页/评论区/客服修复）
- 客单价持续下降 → mission: `aov_lift`（组合购买/套装策略）

---

### A2. AINRL 漏斗分析

**KB依据**：
- 「反漏斗模型优先渗透核心人群」：先渗透最核心人群，再逐层扩展。来源：灵犀学堂 (unit__2be549fe)
- 「一方数据可回传灵犀做深度洞察」：用户资产分析、新客老客流转监控。来源：灵犀学堂 (unit__2be549fe)
- 「利用DMP人群包做未支付用户追投」：加购未支付人群追投可将转化提升2倍。来源：2025精准获客实战 (unit__6d69d32b)

**分析方向**：
1. 各层转化率：A→I→N→R→L 每层转化率与行业基准对比
2. 最大断点定位：哪层漏损最严重
3. 30日增量：哪层在涨/跌

**健康阈值**（珠宝配饰 ramp_up）：

| 转化步骤 | 好 | 警告 | 差 | 来源 |
|----------|------|------|------|------|
| A→I (认知→兴趣) | >25% | 15-25% | <15% | 专业推断（珠宝高客单决策长） |
| I→N (兴趣→新客) | >8% | 4-8% | <4% | 专业推断+Le Fond实际6.9% |
| N→R (新客→复购) | >15% | 5-15% | <5% | KB: repurchase相关KO + Le Fond 3.9%=差 |
| R→L (复购→亲密) | >30% | 15-30% | <15% | 专业推断 |

**触发动作**：
- I→N<4% → mission: `conversion_repair`（商品页优化+评论区挂链）
- N→R<5% → mission: `repurchase_activation`（粉丝群+老客召回）
- A→I<15% → mission: `content_formula_scaling`（内容吸引力不足）

---

### A3. 搜索词分析

**KB依据**：
- 「搜索心智贯穿小红书用户决策链」：近70%月活用户使用搜索，SPU深度种草贡献高达50%。来源：消费品新锐成长营 (unit__2a59b825)
- 「出行场景的进攻性搜索布局策略」：提前1月布局长假搜索词。来源：奢品行业专场 (unit__32a11df5)
- 「品牌心智空间管理与搜索SOV防守」：核心词SOV须>90%，品类词进Top3。来源：奢品行业专场 (unit__32a11df5)
- 「利用灵犀平台捕捉动态蓝海」：分析蓝海关键字供需情况指导选品。来源：消费品新锐成长营 (unit__2a59b825)

**分析方向**：
1. 搜索词生命周期：top词的7日/30日点击趋势
2. 品牌词 vs 品类词 vs 长尾词比例
3. 搜索成交转化率排名：哪些词真正带来GMV
4. 蓝海词机会：高搜索+低竞争的词

**健康阈值**：

| 指标 | 好 | 警告 | 差 | 来源 |
|------|------|------|------|------|
| 搜索成交CTR | >10% | 5-10% | <5% | KB: search_opportunity_ctr=0.10 |
| 品牌词SOV | >90% | 60-90% | <60% | KB: 奢品行业专场 |
| Top10词覆盖GMV | >50% | 30-50% | <30% | 专业推断 |

**触发动作**：
- 品牌词SOV<60% → mission: `search_positioning`（搜索直投防守）
- 发现蓝海词（高搜索低竞争） → 立即产出对应内容
- Top词CTR下降>30% → 更新封面/标题匹配搜索意图

---

### A4. 退款率分析

**KB依据**：
- 「产品品质是口碑种草的胜负手」：品质占消费决策因子第一（87%），不过关会被吐槽劝退。来源：营销的第三种范式 (unit__bb73d770)
- 「小红书用户追求"相对优惠而非绝对低价"」：一二线用户接受一分价钱一分货。来源：珠宝饰品直播经验 (unit__5fc95bc6)

**分析方向**：
1. 退款率趋势：逐月变化方向
2. 退款原因分布：质量问题 / 色差 / 不喜欢 / 物流
3. 退款-SKU关联：哪些SKU退款率高
4. 退款时间分布：签收后多久退

**健康阈值**：

| 指标 | 好 | 警告 | 差 | 来源 |
|------|------|------|------|------|
| 整体退款率 | <10% | 10-15% | >15% | KB: refund_rate_high=0.15 |
| 质量原因退款占比 | <20% | 20-40% | >40% | 专业推断 |
| 英雄SKU退款率 | <8% | 8-12% | >12% | 专业推断（高依赖度SKU要求更严） |

**触发动作**：
- 退款率>15% → 紧急检查商品页描述与实物一致性
- 质量原因>40% → 供应链/QC问题，停止投流该SKU
- 退款率连续2月上升 → 触发完整退款原因分析

---

### A5. 内容-商业联动分析

**KB依据**：
- 「通过转化和流量突破定义爆款笔记」：爆不只看流量，关键是带来实际转化。来源：笔直群联动 (unit__de7571ed)
- 「舍弃CPM与CPC，用CPE作为投放核心指南针」：互动率<3%判低质。来源：2025精准获客实战 (unit__6d69d32b)
- 「搭建按阶梯式CPE和互动成效判断放量的标准」：CPE≥15元淘汰，≤8元+互动率≥5%放量。来源：2025精准获客实战 (unit__6d69d32b)
- 「笔记的三大核心使命：销售、蓄水、引流」：笔记=24小时销售员+直播蓄水池+群聊入口。来源：笔直群联动 (unit__de7571ed)

**分析方向**：
1. 每篇笔记的商业贡献：阅读→进店→成交全链路追踪
2. 内容类型ROI：哲学叙事 vs 产品展示 vs 穿搭场景
3. CPE分级：S/A/B/C四级，指导投流决策
4. 视频 vs 图文的转化效率对比

**健康阈值**：

| 指标 | 好(S/A级) | 可用(B级) | 差(C级) | 来源 |
|------|------|------|------|------|
| CPE | ≤¥8 | ≤¥12 | ≥¥15淘汰 | KB: 2025精准获客实战 |
| 互动率 | ≥5% | ≥3% | <3%低质 | KB: 2025精准获客实战 |
| 笔记→成交转化 | ≥2% | ≥0.5% | <0.5% | 专业推断 |

**触发动作**：
- 发现S级内容 → 立即全渠道放量+复刻模型
- 互动率<3% → 停止投流，转自然流测试
- 哲学叙事类ROI持续最高 → 增加该类型产出比例

---

### A6. 客单价变化分析

**KB依据**：
- 「利用组合购买玩法提升客单价」：第二件半价、捆绑销售。来源：珠宝饰品直播经验 (unit__5fc95bc6)
- 「套装化产品设计降低用户购买决策」：套装提升客单价+降低咨询量。来源：珠宝饰品直播经验 (unit__5fc95bc6)
- 「构建货盘层级：福利、主推、高货复购」：低价拉新→主推承接→高客单复购。来源：珠宝饰品直播经验 (unit__5fc95bc6)
- 「选品应具备决策纠合价点」：需求与价值是第一位，非绝对低价。来源：消费品新锐成长营 (unit__2a59b825)

**分析方向**：
1. AOV趋势：逐月客单价变化
2. 价格带分布：<100 / 100-200 / 200-500 / >500
3. 关联购买率：单笔订单多SKU比例
4. 套装 vs 单品AOV差异

**健康阈值**（Le Fond ¥199主力SKU）：

| 指标 | 好 | 警告 | 差 | 来源 |
|------|------|------|------|------|
| AOV | >¥250 | ¥180-250 | <¥180 | KB: aov_low=300 调整为品牌实际 |
| 多SKU订单占比 | >20% | 10-20% | <10% | 专业推断 |
| AOV MoM变化 | 上升或持平 | 下降<5% | 下降>5% | 专业推断 |

**触发动作**：
- AOV持续<¥180 → mission: `aov_lift`（推套装+组合购买）
- 多SKU比例<10% → 评论区推荐搭配、套装上架
- AOV上升但订单量下降 → 检查是否价格劝退新客

---

## Task B：Opus 分析提示词模板

```markdown
# Revenue OS 数据分析报告生成提示词

你是 Le Fond 银饰品牌的运营分析顾问。请基于以下输入生成结构化分析报告。

## 输入数据

### 1. metrics_snapshot（ETL 输出）
```json
{metrics_snapshot_json}
```

### 2. 相关 KB 知识（由 kb_retriever 检索）
```json
{kb_results_json}
```

### 3. 品牌上下文
- 品牌：Le Fond（银饰 DTC）
- 当前阶段：{stage}（由 infer_stage 推断）
- 英雄SKU：荣格耳钉 ¥199
- 目标月GMV：¥100K

## 分析框架

### Step 1: 指标健康诊断
对以下核心指标逐一评估：
1. **月GMV**：MoM增长率，距¥100K目标差距
2. **进店-支付转化率**：阈值 好>3% / 警告2-3% / 差<2%
3. **AINRL漏斗**：找到最大断点
4. **退款率**：阈值 好<10% / 警告10-15% / 差>15%
5. **客单价**：与¥199锚定价对比
6. **搜索词**：top词CTR变化、蓝海词机会
7. **内容CPE**：S/A/B/C分级
8. **复购率**：N→R转化

每个指标必须输出：
- 当前值
- 健康状态（好/警告/差）
- 变化方向（↑↗→↘↓）
- KB依据引用（格式：[KB:维度/课程名]）

### Step 2: 主要瓶颈识别
从 Step 1 中选出最紧急的 1-2 个瓶颈，说明：
- 为什么这个是最紧急的（数字论证）
- 它阻碍了什么（因果链）
- KB中对此有什么建议

### Step 3: 行动建议（本周）
输出 3 个优先级排序的可执行动作：

| 优先级 | 动作 | 预期效果 | KB依据 | mission_type |
|--------|------|----------|--------|-------------|
| P0 | ... | ... | [KB:...] | ... |
| P1 | ... | ... | [KB:...] | ... |
| P2 | ... | ... | [KB:...] | ... |

每个动作必须：
- 具体到可以今天开始执行
- 有预期量化效果
- 有KB知识支撑
- 映射到 Revenue OS 的 mission_type

### Step 4: 趋势预警
基于历史数据，识别以下信号：
- 增长减速信号（MoM增长率连续下降）
- 退款率上升信号
- 搜索词衰减信号
- 内容疲劳信号（平均阅读量持续下降）

## 输出格式

```markdown
# Le Fond 运营分析报告
> 数据截止：{snapshot_date} | 阶段：{stage} | 置信度：{confidence}

## 📊 核心指标仪表盘
（表格）

## 🔴 主要瓶颈
（2段论述）

## ✅ 本周行动清单
（表格）

## ⚠️ 趋势预警
（bullet list）

## 📚 KB知识引用
（所有引用的KB条目列表）
```

## 约束
- KB知识优先于你的推断
- 每个结论必须有数字支撑
- 行动建议必须可执行（不是"优化XX"，而是"在荣格耳钉商品笔记评论区置顶评论中加入蓝链"）
- 中文输出，不要AI味
```

---

## Task C：健康指标体系

### 核心指标清单（8个）

| # | 指标 | 含义 | 数据源 | KB覆盖维度 |
|---|------|------|--------|-----------|
| 1 | `monthly_gmv` | 月成交金额 | 商家成交概览 | data_analytics |
| 2 | `shop_visit_to_pay_cvr` | 进店-支付转化率 | 商家成交概览 | conversion_path |
| 3 | `aov` | 客单价 | 商家成交概览 | product_strategy |
| 4 | `refund_rate` | 退款率（支付口径） | 退款分析 | product_strategy |
| 5 | `ainrl_i_to_n_cvr` | 兴趣→新客转化率 | AINRL漏斗 | conversion_path |
| 6 | `ainrl_n_to_r_cvr` | 新客→复购转化率 | AINRL漏斗 | account_operation |
| 7 | `content_cpe_median` | 内容CPE中位数 | 笔记数据 | content_creation |
| 8 | `search_brand_sov` | 品牌词SOV | 搜索总览 | traffic_acquisition |

### 健康阈值（ramp_up × 珠宝配饰）

| 指标 | 好 | 警告 | 差 | 来源 |
|------|------|------|------|------|
| monthly_gmv | MoM>30% | MoM 10-30% | MoM<10% | 专业推断 |
| shop_visit_to_pay_cvr | >3% | 2-3% | <2% | KB: config.DEFAULT_THRESHOLDS |
| aov | >¥250 | ¥180-250 | <¥180 | KB: aov_low=300 + 品牌校正 |
| refund_rate | <10% | 10-15% | >15% | KB: refund_rate_high=0.15 |
| ainrl_i_to_n_cvr | >8% | 4-8% | <4% | 专业推断+Le Fond基线 |
| ainrl_n_to_r_cvr | >15% | 5-15% | <5% | KB: repurchase KOs |
| content_cpe_median | ≤¥8 | ¥8-15 | >¥15 | KB: 2025精准获客实战 |
| search_brand_sov | >90% | 60-90% | <60% | KB: 奢品行业专场 |

### 指标依赖关系（诊断顺序）

```
monthly_gmv  ←  shop_visit_to_pay_cvr  ←  content_cpe_median
     ↑                   ↑                       ↑
    aov            ainrl_i_to_n_cvr        search_brand_sov
     ↑                   ↑
 refund_rate      ainrl_n_to_r_cvr
```

**诊断优先级**：
1. 先看 `shop_visit_to_pay_cvr`（最直接影响GMV的转化效率）
2. 如果转化率OK，看 `ainrl_i_to_n_cvr`（流量到客户的转化）
3. 如果新客OK，看 `ainrl_n_to_r_cvr`（复购=LTV放大器）
4. 横向检查 `refund_rate`（侵蚀利润+口碑）
5. 检查 `content_cpe_median`（内容投放效率）
6. 检查 `search_brand_sov`（搜索防守）
7. 综合看 `aov`（客单价提升空间）
8. 最终汇总 `monthly_gmv`（结果指标）

### 珠宝配饰行业特殊调整

| 调整项 | 通用标准 | 珠宝调整 | 原因 | KB依据 |
|--------|---------|---------|------|--------|
| 转化周期 | 7天 | 14-30天 | 高客单决策长 | KB: 搜索心智贯穿决策链 |
| 复购周期 | 30天 | 90天 | 饰品非高频消费 | 专业推断 |
| 退款率阈值 | 15% | 12% | 手工制品退款风险高 | KB: 产品品质是胜负手 |
| 内容类型权重 | 均等 | 叙事视频>展示图文 | 珠宝需故事+情感溢价 | KB: 珠宝叠戴搜索增长110% |
| 季节性 | 618/双11 | +礼赠节+婚嫁季 | 珠宝四大场景贯穿全年 | KB: 珠宝腕表四大场景 |

---

## Task D：历史趋势分析规则

### D1. 增长加速/减速判断逻辑

```python
def growth_signal(gmv_series: list[float]) -> str:
    """
    gmv_series: 按月排列的GMV值，至少3个月
    返回: accelerating | steady | decelerating | declining
    """
    if len(gmv_series) < 3:
        return "insufficient_data"
    
    mom_rates = []
    for i in range(1, len(gmv_series)):
        prev = gmv_series[i-1]
        if prev > 0:
            mom_rates.append((gmv_series[i] - prev) / prev)
        else:
            mom_rates.append(float('inf') if gmv_series[i] > 0 else 0)
    
    latest_2 = mom_rates[-2:]
    
    if all(r > 0.3 for r in latest_2):
        return "accelerating"      # 连续2月>30%增长
    elif all(r > 0 for r in latest_2):
        if latest_2[-1] > latest_2[-2]:
            return "accelerating"  # 增长率在加速
        else:
            return "decelerating"  # 还在涨但速度放慢
    elif latest_2[-1] < 0:
        return "declining"         # 最近一月负增长
    else:
        return "steady"
```

**来源**：KB「破冰期后的经营逻辑跃迁」+ 专业推断

### D2. 季节性调整（中国节假日）

```python
SEASONAL_EVENTS = {
    "01": {"event": "元旦+年货节", "gmv_lift": 0.15, "note": "礼赠场景"},
    "02": {"event": "春节+情人节", "gmv_lift": 0.30, "note": "珠宝礼赠高峰"},
    "03": {"event": "妇女节+开学季", "gmv_lift": 0.10, "note": "悦己消费"},
    "04": {"event": "春季上新", "gmv_lift": 0.05, "note": "穿搭换季"},
    "05": {"event": "母亲节+520", "gmv_lift": 0.25, "note": "KB:送母亲趋势增长"},
    "06": {"event": "618+端午", "gmv_lift": 0.20, "note": "大促"},
    "07": {"event": "暑期", "gmv_lift": 0.00, "note": "平季"},
    "08": {"event": "七夕", "gmv_lift": 0.20, "note": "珠宝第二峰"},
    "09": {"event": "开学+中秋", "gmv_lift": 0.10, "note": "KB:四大场景之礼赠"},
    "10": {"event": "国庆+出行", "gmv_lift": 0.15, "note": "KB:出行场景布局"},
    "11": {"event": "双11", "gmv_lift": 0.35, "note": "全年最大促"},
    "12": {"event": "双12+圣诞+跨年", "gmv_lift": 0.20, "note": "KB:双蛋节点"},
}

def seasonal_adjusted_growth(raw_mom: float, month: str) -> float:
    """去除季节性后的真实增长率"""
    lift = SEASONAL_EVENTS.get(month, {}).get("gmv_lift", 0)
    return raw_mom - lift
```

**来源**：KB「珠宝腕表由四大场景贯穿全年营销」(unit__32a11df5) + KB「礼赠场景新增送母亲与悦己趋势」(unit__32a11df5)

### D3. 退款率趋势解读

```python
def refund_trend_signal(refund_rates: list[float]) -> dict:
    """
    refund_rates: 按月排列的退款率，至少2个月
    返回诊断信号
    """
    if len(refund_rates) < 2:
        return {"signal": "insufficient", "action": "continue_monitoring"}
    
    latest = refund_rates[-1]
    prev = refund_rates[-2]
    trend = "rising" if latest > prev * 1.1 else ("falling" if latest < prev * 0.9 else "stable")
    
    # KB: refund_rate_high = 0.15
    if latest > 0.15:
        severity = "critical"
        action = "immediate_sku_review"
    elif latest > 0.10 and trend == "rising":
        severity = "warning"
        action = "investigate_refund_reasons"
    elif latest > 0.10:
        severity = "caution"
        action = "monitor_weekly"
    else:
        severity = "healthy"
        action = "maintain"
    
    return {
        "signal": trend,
        "severity": severity,
        "action": action,
        "latest_rate": latest,
        "mom_change": latest - prev,
    }
```

**来源**：KB「产品品质是口碑种草的胜负手」(unit__bb73d770) + config.DEFAULT_THRESHOLDS

### D4. 搜索词生命周期分析

```python
def search_term_lifecycle(term_history: list[dict]) -> str:
    """
    term_history: [{"month": "2026-01", "clicks": 120, "cvr": 0.05}, ...]
    返回: emerging | peak | declining | dead
    """
    if len(term_history) < 2:
        return "new"
    
    clicks = [t["clicks"] for t in term_history]
    latest_mom = (clicks[-1] - clicks[-2]) / max(clicks[-2], 1)
    peak_clicks = max(clicks)
    
    if latest_mom > 0.3:
        return "emerging"     # 快速增长
    elif clicks[-1] >= peak_clicks * 0.8:
        return "peak"         # 处于或接近峰值
    elif clicks[-1] >= peak_clicks * 0.4:
        return "declining"    # 从峰值回落
    else:
        return "dead"         # 流量枯竭
```

**触发动作**：
- `emerging` → 立即加大该词内容覆盖（KB: 搜索布局提前1月）
- `peak` → 维持投放，准备替代词
- `declining` → 减少投放，寻找新蓝海词（KB: 灵犀捕捉动态蓝海）
- `dead` → 停止投放，回收预算

**来源**：KB「搜索心智贯穿用户决策链」(unit__2a59b825) + KB「出行场景搜索布局」(unit__32a11df5) + 专业推断

---

## 附录：KB来源索引

| 引用ID | 课程名 | 维度 | unit_id |
|--------|--------|------|---------|
| 消费品新锐成长营 | 平台认知+开店+起号+人群+选题+写笔记 | 多维度 | unit__2a59b825 |
| 珠宝饰品直播经验 | 文玩玉翠 珠宝饰品直播经验大公开 | 多维度 | unit__5fc95bc6 |
| 奢品行业专场 | 奢品行业专场丨小红书双11种草学习季 | traffic_acquisition | unit__32a11df5 |
| 2025精准获客实战 | 2025小红书精准获客实战秘籍 | traffic_acquisition | unit__6d69d32b |
| 灵犀学堂 | 灵犀学堂丨找准人、发现人的决策因子 | traffic_acquisition | unit__2be549fe |
| 笔直群联动 | 笔直群联动打造高效生意闭环 | conversion_path | unit__de7571ed |
| 营销第三范式 | 营销的第三种范式 | product_strategy | unit__bb73d770 |
| 聚光APP宝典 | 聚光 APP 使用宝典 | data_analytics | unit__76bcd484 |
| 买手橱窗装修 | 小红书买手橱窗装修指南 | conversion_path | unit__8e1a8b05 |
