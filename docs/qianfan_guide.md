# 千帆数据导出指南

以下指标 opencli 无法自动采集，需从千帆后台手动查询后填入 `brand_profile.yaml`。

## 查询路径

| 指标 | 千帆路径 |
|------|---------|
| `shop_visit_to_pay_cvr` 进店→购买转化率 | 千帆后台 → 交易分析 → 转化漏斗 |
| `product_click_to_pay_cvr` 商品点击→购买 | 千帆后台 → 商品分析 → 转化率 |
| `search_ctr` 搜索点击率 | 千帆后台 → 搜索分析 → 关键词报表 |
| `aov` 客单价 | 千帆后台 → 交易分析 → 概览 |
| `repurchase_rate` 30天复购率 | 千帆后台 → 用户分析 → 复购率 |

## 填写方式

查到数据后，在 `brand_profile.yaml` 的 `metrics` 段填入：

```yaml
metrics:
  shop_visit_to_pay_cvr: 0.0096   # 0.96%
  aov: 199
  search_ctr: 0.045
```
