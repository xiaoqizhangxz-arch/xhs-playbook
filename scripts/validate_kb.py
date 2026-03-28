#!/usr/bin/env python3
"""验证 knowledge_base 格式完整性"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MERGED = ROOT / "knowledge_base/canonical/_merged_all.json"
INDEX  = ROOT / "knowledge_base/indices/inverted_index.json"
IDF    = ROOT / "knowledge_base/indices/idf_index.json"

errors = []

# 1. 必要文件存在
for p in [MERGED, INDEX, IDF]:
    if not p.exists():
        errors.append(f"缺少文件: {p}")

if errors:
    print("\n".join(errors)); sys.exit(1)

# 2. KO 字段完整性
data = json.loads(MERGED.read_text(encoding="utf-8"))
total = 0
for dim, kos in data.items():
    for i, ko in enumerate(kos):
        for field in ("insight", "detail", "dimension", "confidence"):
            if not ko.get(field):
                errors.append(f"{dim}[{i}] 缺少字段: {field}")
        total += 1

print(f"✅ KO总数: {total}")
print(f"✅ 维度数: {len(data)}")
if errors:
    print(f"❌ {len(errors)} 个错误:")
    for e in errors[:10]: print(" ", e)
    sys.exit(1)
else:
    print("✅ 格式校验通过")
