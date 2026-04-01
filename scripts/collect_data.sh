#!/bin/bash
# collect_data.sh — XHS 数据全量采集入口
#
# 前提条件：
#   - Chrome Tab: creator.xiaohongshu.com（已登录）
#   - Chrome Tab: ark.xiaohongshu.com（已登录）
#   - opencli daemon 运行中（opencli doctor 确认，Browser Bridge Connected）
#   - macOS Chrome Apple 事件 JS 权限已开启
#
# 已知限制（2026-03-31 验证）：
#   - 千帆图表全为 SVG 路径渲染，DOM 无数值，不支持自动 OCR
#   - 人群画像（性别/年龄/地域）需手动从千帆导出 PDF
#   - 成交分析 tab（载体/账号/人群构成）为懒加载 SVG，tab 点击后仍无 DOM 数值
#   - AINRL 用户资产漏斗在 innerText 里，可直接采集
#
# 采集覆盖（自动）：
#   Creator: stats / notes(100条) / note-detail(逐篇)
#   千帆: 22个页面 DOM innerText（monthly mode）
#   千帆历史: xhs_historical_collector.py --start YYYY-MM-01 --end YYYY-MM-31
#
# 不可自动采集（需手动导出）：
#   人群画像 PDF → 千帆「人群构成」tab → 下载数据

set -e
mkdir -p data/creator data/ark data/structured

echo "════════════════════════════════════"
echo " XHS 数据采集  $(date +%Y-%m-%d)"
echo "════════════════════════════════════"

# ── 1. Creator 数据 ──────────────────────────────────────
echo ""
echo "[1] Creator 数据采集..."
opencli xiaohongshu creator-stats -f json > data/creator/creator_stats_$(date +%Y-%m-%d).json \
  && echo "  ✅ creator-stats"

opencli xiaohongshu creator-notes --limit 100 -f json > data/creator/creator_notes_$(date +%Y-%m-%d).json \
  && echo "  ✅ creator-notes (100条)"

# note-detail 逐篇（从 creator_notes 取 noteId）
python3 - << 'PYEOF'
import json, subprocess, time, os
from pathlib import Path

date = __import__('datetime').date.today().strftime('%Y-%m-%d')
notes_file = f"data/creator/creator_notes_{date}.json"
out_dir = Path("data/creator/note_details")
out_dir.mkdir(exist_ok=True)

with open(notes_file) as f:
    notes = json.load(f)

print(f"  采集 {len(notes)} 篇笔记详情...")
for i, note in enumerate(notes):
    note_id = note.get('noteId') or note.get('id') or note.get('note_id')
    if not note_id:
        continue
    out_file = out_dir / f"{note_id}.json"
    if out_file.exists():
        continue
    r = subprocess.run(['opencli', 'xiaohongshu', 'creator-note-detail', note_id, '-f', 'json'],
                       capture_output=True, text=True, timeout=30)
    if r.returncode == 0 and r.stdout.strip():
        out_file.write_text(r.stdout)
    time.sleep(2)
print(f"  ✅ note-detail 完成")
PYEOF

# ── 2. 千帆月度快照 ──────────────────────────────────────
echo ""
echo "[2] 千帆月度快照（monthly mode）..."
echo "  需要 Chrome 已打开 ark.xiaohongshu.com（Tab 8）"
python3 -m revenue_os.acquisition.xhs_full_collector --mode monthly \
  && echo "  ✅ 千帆月度采集完成（22页）"

# ── 3. 千帆历史数据（月初运行） ──────────────────────────
echo ""
echo "[3] 千帆历史数据（上月完整）..."
LAST_MONTH_START=$(date -v-1m +%Y-%m-01 2>/dev/null || date --date="last month" +%Y-%m-01)
LAST_MONTH_END=$(date -v-1d +%Y-%m-%d 2>/dev/null || date --date="yesterday" +%Y-%m-%d)
python3 -m revenue_os.acquisition.xhs_historical_collector \
  --start "$LAST_MONTH_START" --end "$LAST_MONTH_END" \
  && echo "  ✅ 历史数据采集完成"

# ── 4. DOM 结构化 ─────────────────────────────────────────
echo ""
echo "[4] DOM 文本结构化（Gemini）..."
python3 - << 'PYEOF'
import json, os, http.client, re, time
from pathlib import Path
from datetime import date

today = date.today().strftime('%Y-%m-%d')
GEMINI_KEY = os.environ.get('GEMINI_API_KEY', '')
if not GEMINI_KEY:
    print("  ⚠️  GEMINI_API_KEY 未设置，跳过结构化")
    exit(0)

ark_dir = Path("data/ark")
out_dir = Path(f"data/structured/{today}")
out_dir.mkdir(parents=True, exist_ok=True)

for txt_file in ark_dir.glob(f"{today}_*.txt"):
    label = txt_file.stem.replace(f"{today}_", "")
    text = txt_file.read_text()
    if len(text) < 200:
        continue
    prompt = f'提取「{label}」页面业务数据为JSON，忽略导航/按钮文字：{{"page":"{label}","time_range":"","key_metrics":[{{"name":"","value":"","unit":"","change":""}}]}}\n内容：\n{text[:3000]}'
    payload = json.dumps({"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"maxOutputTokens":1024,"temperature":0.1}}).encode()
    try:
        conn = http.client.HTTPSConnection("generativelanguage.googleapis.com", timeout=60)
        conn.request("POST", f"/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
                     body=payload, headers={"Content-Type":"application/json"})
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        result_text = json.loads(body)['candidates'][0]['content']['parts'][0]['text']
        m = re.search(r'\{.*\}', result_text, re.DOTALL)
        if m:
            result = json.loads(m.group())
            (out_dir / f"{label}_structured.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2))
            print(f"  ✅ {label}: {len(result.get('key_metrics',[]))}个指标")
        time.sleep(1.2)
    except Exception as e:
        print(f"  ⚠️  {label}: {e}")
PYEOF

echo ""
echo "════════════════════════════════════"
echo " ✅ 采集完成！运行诊断："
echo "    python skills/diagnose/scripts/diagnose.py"
echo ""
echo " ⚠️  需手动补充："
echo "    人群画像（性别/年龄/地域）→ 千帆「成交分析→人群构成」→ 下载数据"
echo "════════════════════════════════════"
