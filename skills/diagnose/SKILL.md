# /diagnose — 账号健康诊断

## 描述
读取 brand_profile.yaml + data/ 目录的 opencli 数据，输出：
- 健康总分（0-100）+ 5维度明细
- 主要瓶颈（当前值 vs 行业基准）
- Top 3 KB 知识支撑（官方课程依据）

无数据时进入冷启动模式，基于行业+阶段先验给出初步建议。

## 触发
用户输入 `/diagnose`

## 用法
```bash
# 采集数据（推荐先做）
opencli xiaohongshu creator-stats -f json > data/creator_stats.json
opencli xiaohongshu creator-notes --limit 50 -f json > data/creator_notes.json

# 运行诊断
python skills/diagnose/scripts/diagnose.py
```

## 输出
- 终端打印诊断报告
- `runtime/last_diagnose.md` + `runtime/last_diagnose.json`（供 /brief 复用）
