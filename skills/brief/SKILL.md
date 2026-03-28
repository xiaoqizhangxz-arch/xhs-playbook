# /brief — 本周执行简报

## 描述
基于诊断结果，从 6,429 条 KB 知识中检索并排序，输出本周3个优先执行建议。
每个建议包含：做什么 / 为什么 / 执行成本 / 预估效果 / KB 知识来源。

## 触发
用户输入 `/brief`（建议先运行 `/diagnose`）

## 用法
```bash
python skills/brief/scripts/brief.py
```

## 输出
- 终端打印本周简报
- `runtime/last_brief.md`
