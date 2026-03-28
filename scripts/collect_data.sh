#!/bin/bash
# 一键采集 opencli 账号数据
mkdir -p data
echo "正在采集账号数据..."
opencli xiaohongshu creator-stats -f json > data/creator_stats.json && echo "✅ creator-stats"
opencli xiaohongshu creator-notes --limit 50 -f json > data/creator_notes.json && echo "✅ creator-notes (50条)"
echo ""
echo "采集完成。运行 /diagnose 查看诊断结果："
echo "  python skills/diagnose/scripts/diagnose.py"
