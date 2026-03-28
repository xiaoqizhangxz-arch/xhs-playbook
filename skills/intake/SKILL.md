# /intake — 品牌配置

## 描述
首次使用 Revenue OS 时运行，填写品牌问卷，生成 `brand_profile.yaml`。

## 触发
用户输入 `/intake`

## 用法
```bash
python skills/intake/scripts/intake.py
```

## 输出
- `brand_profile.yaml`（项目根目录）
- 包含：账号基本面 / 核心指标 / 目标约束 / 系统推断（inferred 块）

## 耗时
约 5 分钟（Section 2/3 可跳过）

## 后续
运行 `/diagnose` 获取诊断报告
