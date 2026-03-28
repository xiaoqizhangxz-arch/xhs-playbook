#!/usr/bin/env python3
"""从含 quotation 的完整 KB 生成开源发布版（仅 insight+detail）"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC  = ROOT / "knowledge_base/canonical/_merged_all_full.json"
DST  = ROOT / "knowledge_base/canonical/_merged_all.json"

if not SRC.exists():
    print(f"源文件不存在: {SRC}"); sys.exit(1)

src = json.loads(SRC.read_text(encoding="utf-8"))
REMOVE = {"quotation"}
pub = {dim: [{k: v for k, v in ko.items() if k not in REMOVE} for ko in kos]
       for dim, kos in src.items()}
DST.write_text(json.dumps(pub, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
total = sum(len(v) for v in pub.values())
print(f"✅ 生成 {DST.name}: {total} 条 KO（已移除 quotation）")
