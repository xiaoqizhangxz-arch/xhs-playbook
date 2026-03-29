"""
update_data.py  —  /update-data 全量数据更新入口

分层采集，增量识别，去重入库，完成后输出 coverage 报告。

用法：
  python update_data.py [--from YYYY-MM-DD] [--to YYYY-MM-DD]
                        [--layer creator|ark|users|all]
                        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ── paths ─────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_PLAYBOOK_DIR = _SCRIPT_DIR.parent.parent  # xhs-playbook/
_ROS_SCRIPTS = Path(os.environ.get(
    "ROS_SCRIPTS",
    str(Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
        "/Thoth_Academy_Obsidian/Revenue OS/scripts")
))
sys.path.insert(0, str(_ROS_SCRIPTS))

RUNTIME_DIR = _PLAYBOOK_DIR / "runtime"
RUNTIME_DIR.mkdir(exist_ok=True)
MANIFEST_PATH = RUNTIME_DIR / "update_manifest.json"
LAST_UPDATE_PATH = RUNTIME_DIR / "last_update.json"


# ── manifest: tracks last successful run per layer ────────────────────────────
def _load_manifest() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except Exception:
            pass
    return {"runs": [], "last_success_by_layer": {}}


def _save_manifest(manifest: dict[str, Any]) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def _last_success_date(layer: str, manifest: dict[str, Any]) -> date | None:
    ts = manifest.get("last_success_by_layer", {}).get(layer)
    if ts:
        try:
            return datetime.fromisoformat(ts).date()
        except Exception:
            pass
    return None


def _compute_window(layer: str, manifest: dict[str, Any],
                    override_from: str | None, override_to: str | None) -> tuple[str, str]:
    today = date.today()
    if override_from and override_to:
        return override_from, override_to
    last = _last_success_date(layer, manifest)
    date_from = (last + timedelta(days=1)) if last else (today - timedelta(days=30))
    return date_from.isoformat(), today.isoformat()


# ── run helpers ───────────────────────────────────────────────────────────────
def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 300,
         env: dict | None = None) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, **(env or {})})
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except Exception as e:
        return -2, "", str(e)


# ── Layer 1: Creator API (opencli, fast) ─────────────────────────────────────
def run_creator_api(date_from: str, date_to: str, dry_run: bool) -> dict[str, Any]:
    print("\n[Layer 1] Creator API (opencli)")
    results = {}
    commands = {
        "creator_stats": ["opencli", "xiaohongshu", "creator-stats", "-f", "json"],
        "creator_profile": ["opencli", "xiaohongshu", "creator-profile", "-f", "json"],
        "creator_notes": ["opencli", "xiaohongshu", "creator-notes", "--limit", "200", "-f", "json"],
        "creator_notes_summary": ["opencli", "xiaohongshu", "creator-notes-summary", "-f", "json"],
    }
    for key, cmd in commands.items():
        if dry_run:
            print(f"  [DRY] {' '.join(cmd)}")
            results[key] = {"status": "dry_run"}
            continue
        print(f"  ▶ {key}...", end=" ", flush=True)
        code, stdout, stderr = _run(cmd, timeout=60)
        if code == 0 and stdout.strip():
            # Save to raw_data/creator_auto/api/
            api_dir = Path(os.environ.get(
                "CREATOR_AUTO_ROOT",
                str(Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
                    "/Thoth_Academy_Obsidian/Revenue OS/raw_data/creator_auto/api")
            ))
            api_dir.mkdir(parents=True, exist_ok=True)
            out_path = api_dir / f"{date.today().isoformat()}_{key}.json"
            out_path.write_text(stdout, encoding="utf-8")
            data = json.loads(stdout) if stdout.strip().startswith("[") or stdout.strip().startswith("{") else {}
            count = len(data) if isinstance(data, list) else 1
            print(f"✅ {count} records → {out_path.name}")
            results[key] = {"status": "ok", "file": str(out_path), "count": count}
        else:
            print(f"❌ code={code} {stderr[:100]}")
            results[key] = {"status": "error", "code": code, "stderr": stderr[:200]}
    return results


# ── Layer 2: Creator Browser Context (playwright via creator_capture) ─────────
def run_creator_browser(date_from: str, date_to: str, dry_run: bool) -> dict[str, Any]:
    print("\n[Layer 2] Creator Browser Context (playwright)")
    if dry_run:
        print("  [DRY] acquire_creator(mode='weekly', browser_mode='browser')")
        print("  [DRY] canvas_ocr.py --all-stats")
        return {"status": "dry_run"}

    results = {}
    try:
        from revenue_os.acquisition.creator_capture import acquire_creator
        print("  ▶ creator_home + creator_note_manager (scroll-based)...", flush=True)
        manifest = acquire_creator(mode="weekly", browser_mode="browser")
        print(f"  ✅ status={manifest.get('status')} files={len(manifest.get('downloaded_files', []))}")
        results["browser_capture"] = {
            "status": manifest.get("status"),
            "files": manifest.get("downloaded_files", []),
        }
    except Exception as e:
        print(f"  ❌ creator_capture: {e}")
        results["browser_capture"] = {"status": "error", "error": str(e)}

    # Canvas OCR for stats surfaces
    try:
        from revenue_os.acquisition.canvas_ocr import run_canvas_ocr
        for surface_name in ["creator_stats_overview", "creator_stats_fans", "creator_stats_content"]:
            print(f"  ▶ canvas_ocr {surface_name}...", flush=True)
            try:
                ocr_result = run_canvas_ocr(surface_name, date_from=date_from, date_to=date_to)
                pages = len(ocr_result.get("pages", []))
                print(f"  ✅ {pages} pages OCR'd")
                results[f"ocr_{surface_name}"] = {"status": "ok", "pages": pages}
            except Exception as e:
                print(f"  ❌ {e}")
                results[f"ocr_{surface_name}"] = {"status": "error", "error": str(e)}
    except ImportError as e:
        print(f"  ⚠️ canvas_ocr import failed: {e}")

    return results


# ── Layer 3: ARK DOM text (xhs_historical_collector.py) ───────────────────────
def run_ark_dom(date_from: str, date_to: str, dry_run: bool) -> dict[str, Any]:
    print(f"\n[Layer 3] ARK DOM 文字采集  {date_from} → {date_to}")
    collector_path = _ROS_SCRIPTS / "revenue_os/acquisition/xhs_historical_collector.py"
    if not collector_path.exists():
        print(f"  ❌ 找不到 {collector_path}")
        return {"status": "not_found"}

    if dry_run:
        print(f"  [DRY] python {collector_path.name} --from {date_from} --to {date_to}")
        return {"status": "dry_run"}

    print("  ▶ 运行历史采集脚本...", flush=True)
    code, stdout, stderr = _run(
        [sys.executable, str(collector_path), "--from", date_from, "--to", date_to],
        cwd=_ROS_SCRIPTS, timeout=3600,
    )
    if code == 0:
        lines = stdout.count("✅")
        print(f"  ✅ 完成 ({lines} 成功)")
        return {"status": "ok", "stdout_lines": lines}
    else:
        print(f"  ❌ code={code}\n{stderr[:300]}")
        return {"status": "error", "code": code, "stderr": stderr[:400]}


# ── Layer 4: ARK XLSX download ────────────────────────────────────────────────
def run_ark_xlsx(date_from: str, date_to: str, dry_run: bool) -> dict[str, Any]:
    print(f"\n[Layer 4] ARK XLSX 下载  {date_from} → {date_to}")
    xlsx_script = _ROS_SCRIPTS / "revenue_os/acquisition/download_xlsx.mjs"
    if not xlsx_script.exists():
        print(f"  ❌ 找不到 {xlsx_script}")
        return {"status": "not_found"}

    if dry_run:
        print(f"  [DRY] node {xlsx_script.name} --dry-run")
        return {"status": "dry_run"}

    # TODO: pass date_from/date_to to download_xlsx.mjs (需要日历设置逻辑)
    # 当前先下载默认时间窗口
    print("  ▶ 下载 XLSX（默认时间窗口，日历设置待完善）...", flush=True)
    code, stdout, stderr = _run(
        ["node", str(xlsx_script)],
        cwd=_ROS_SCRIPTS, timeout=600,
    )
    ok_count = stdout.count("✅")
    skip_count = stdout.count("⚠️")
    if code == 0:
        print(f"  ✅ 下载 {ok_count} 个，跳过 {skip_count} 个")
        return {"status": "ok", "downloaded": ok_count, "skipped": skip_count}
    else:
        print(f"  ❌ code={code}\n{stderr[:200]}")
        return {"status": "error", "code": code}


# ── Layer 5: User analysis snapshot ───────────────────────────────────────────
def run_user_snapshot(dry_run: bool) -> dict[str, Any]:
    print("\n[Layer 5] 用户分析快照（人群分层 + AINRL）")
    snapshot_script = _ROS_SCRIPTS / "revenue_os/acquisition/collect_user_pages.mjs"
    if not snapshot_script.exists():
        print(f"  ❌ 找不到 {snapshot_script}")
        return {"status": "not_found"}
    if dry_run:
        print(f"  [DRY] node {snapshot_script.name}")
        return {"status": "dry_run"}
    print("  ▶ 采集用户分析...", flush=True)
    code, stdout, stderr = _run(["node", str(snapshot_script)],
                                cwd=_ROS_SCRIPTS, timeout=600)
    ok_count = stdout.count("✅")
    if code == 0:
        print(f"  ✅ {ok_count} 个文件")
        return {"status": "ok", "files": ok_count}
    else:
        print(f"  ❌ {stderr[:200]}")
        return {"status": "error"}


# ── Coverage report ───────────────────────────────────────────────────────────
def build_coverage_report(run_results: dict[str, Any]) -> str:
    lines = [
        f"\n{'='*60}",
        f"📊 数据更新报告  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"{'='*60}",
    ]
    covered = []
    partial = []
    not_covered = []

    layer_map = {
        "layer1_creator_api": {
            "label": "Creator API (账号/笔记统计)",
            "checks": ["creator_stats", "creator_notes"],
        },
        "layer2_creator_browser": {
            "label": "Creator Browser (首页/笔记管理/统计图表)",
            "checks": ["browser_capture", "ocr_creator_stats_fans"],
        },
        "layer3_ark_dom": {
            "label": "千帆 DOM 文字 (23个数据页)",
            "checks": ["status"],
        },
        "layer4_ark_xlsx": {
            "label": "千帆 XLSX 下载 (14个页面)",
            "checks": ["status"],
        },
        "layer5_user_snapshot": {
            "label": "用户分析快照 (人群分层+AINRL)",
            "checks": ["status"],
        },
    }

    for layer_key, info in layer_map.items():
        layer_result = run_results.get(layer_key, {})
        status = layer_result.get("status", "not_run")
        if status in ("ok", "success"):
            covered.append(info["label"])
            lines.append(f"  ✅ {info['label']}")
        elif status == "dry_run":
            lines.append(f"  🔵 {info['label']} [dry-run]")
        elif status in ("not_found", "not_run"):
            not_covered.append(info["label"])
            lines.append(f"  ⚪ {info['label']} [未运行]")
        else:
            partial.append(info["label"])
            err = layer_result.get("error", layer_result.get("stderr", ""))[:60]
            lines.append(f"  ⚠️  {info['label']} [部分失败: {err}]")

    lines.append(f"\n{'─'*60}")
    lines.append(f"✅ 完整覆盖: {len(covered)}/5 层")

    not_yet = [
        "⛔ 千帆 XLSX 跨月日历设置（待解决跨月问题）",
        "⛔ creator statistics 日期范围设置（canvas OCR 日期参数化）",
    ]
    if not_yet:
        lines.append("\n尚未解决:")
        lines.extend(f"  {x}" for x in not_yet)

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="/update-data 全量数据更新")
    parser.add_argument("--from", dest="date_from", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--layer", choices=["creator", "ark", "users", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = _load_manifest()
    run_results: dict[str, Any] = {}
    start_time = datetime.now()

    print(f"\n{'='*60}")
    print(f"/update-data  {'[DRY RUN] ' if args.dry_run else ''}开始")
    print(f"{'='*60}")

    # Layer 1: Creator API
    if args.layer in ("creator", "all"):
        date_from, date_to = _compute_window("layer1", manifest, args.date_from, args.date_to)
        print(f"  时间窗口: {date_from} → {date_to}")
        results1 = run_creator_api(date_from, date_to, args.dry_run)
        run_results["layer1_creator_api"] = results1
        if all(v.get("status") == "ok" for v in results1.values()):
            run_results["layer1_creator_api"]["status"] = "ok"
            manifest.setdefault("last_success_by_layer", {})["layer1"] = datetime.now().isoformat()

    # Layer 2: Creator Browser
    if args.layer in ("creator", "all"):
        date_from, date_to = _compute_window("layer2", manifest, args.date_from, args.date_to)
        results2 = run_creator_browser(date_from, date_to, args.dry_run)
        run_results["layer2_creator_browser"] = results2
        if results2.get("browser_capture", {}).get("status") in ("success", "ok"):
            manifest.setdefault("last_success_by_layer", {})["layer2"] = datetime.now().isoformat()
            run_results["layer2_creator_browser"]["status"] = "ok"

    # Layer 3: ARK DOM
    if args.layer in ("ark", "all"):
        date_from, date_to = _compute_window("layer3", manifest, args.date_from, args.date_to)
        results3 = run_ark_dom(date_from, date_to, args.dry_run)
        run_results["layer3_ark_dom"] = results3
        if results3.get("status") == "ok":
            manifest.setdefault("last_success_by_layer", {})["layer3"] = datetime.now().isoformat()

    # Layer 4: ARK XLSX
    if args.layer in ("ark", "all"):
        date_from, date_to = _compute_window("layer4", manifest, args.date_from, args.date_to)
        results4 = run_ark_xlsx(date_from, date_to, args.dry_run)
        run_results["layer4_ark_xlsx"] = results4
        if results4.get("status") == "ok":
            manifest.setdefault("last_success_by_layer", {})["layer4"] = datetime.now().isoformat()

    # Layer 5: User Snapshot
    if args.layer in ("users", "all"):
        results5 = run_user_snapshot(args.dry_run)
        run_results["layer5_user_snapshot"] = results5
        if results5.get("status") == "ok":
            manifest.setdefault("last_success_by_layer", {})["layer5"] = datetime.now().isoformat()

    # Save manifest + last_update
    elapsed = (datetime.now() - start_time).total_seconds()
    run_record = {
        "run_at": start_time.isoformat(),
        "elapsed_seconds": round(elapsed),
        "dry_run": args.dry_run,
        "layer": args.layer,
        "results": run_results,
    }
    manifest.setdefault("runs", []).append({
        "run_at": start_time.isoformat(),
        "elapsed_seconds": round(elapsed),
        "layer": args.layer,
        "dry_run": args.dry_run,
    })
    # Keep only last 50 runs
    manifest["runs"] = manifest["runs"][-50:]
    _save_manifest(manifest)
    LAST_UPDATE_PATH.write_text(json.dumps(run_record, indent=2, ensure_ascii=False))

    # Print coverage report
    report = build_coverage_report(run_results)
    print(report)
    print(f"\n⏱  耗时 {elapsed:.0f}s")
    print(f"📁 详情: {LAST_UPDATE_PATH}")


if __name__ == "__main__":
    main()
