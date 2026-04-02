"""
calibration.py — 校准参数注册表（从 stub 升级为可读参数）

校准数据来源优先级：
  1. config/calibration/*.yaml（人工校准文件，若存在）
  2. 内置默认值（基于 Le Fond 5个月真实数据估算）

使用方式：
  from revenue_os.modeling.calibration import CALIBRATION_BUCKET, calibration_ref, get_prior

覆盖方式（开源用户）：
  在项目根创建 config/calibration/domain.yaml，格式见 _DEFAULT_CALIBRATION
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CALIBRATION_VERSION = "p1.calibration.v1"
CALIBRATION_BUCKET = "small_sample_bayes_informed"  # 从 uncalibrated 升级


# ── 内置默认先验（基于 Le Fond 2025-10 ~ 2026-03 历史数据） ─────────────────
# 含义：pool_mean = 行业小样本期望值；prior_strength = 伪样本数（信念强度）
_DEFAULT_CALIBRATION: dict[str, Any] = {
    "metric_priors": {
        "shop_visit_to_pay_cvr": {
            "pool_mean": 0.012,       # 珠宝 DTC ramp_up 实测均值
            "prior_strength": 8.0,
            "note": "le_fond_5mo_observed",
        },
        "product_click_to_pay_cvr": {
            "pool_mean": 0.03,
            "prior_strength": 6.0,
            "note": "le_fond_estimate",
        },
        "inquiry_to_pay_cvr": {
            "pool_mean": 0.18,
            "prior_strength": 5.0,
            "note": "industry_typical",
        },
        "aov": {
            "pool_mean": 210.0,
            "prior_strength": 4.0,
            "note": "le_fond_hero_sku_199",
        },
        "refund_rate": {
            "pool_mean": 0.11,
            "prior_strength": 6.0,
            "note": "le_fond_5mo_observed",
        },
        "repurchase_rate": {
            "pool_mean": 0.04,
            "prior_strength": 4.0,
            "note": "le_fond_observed_low",
        },
        "search_ctr": {
            "pool_mean": 0.09,
            "prior_strength": 5.0,
            "note": "industry_typical",
        },
        "cover_ctr": {
            "pool_mean": 0.07,
            "prior_strength": 5.0,
            "note": "industry_typical",
        },
        "recent_note_median_views": {
            "pool_mean": 450.0,
            "prior_strength": 3.0,
            "note": "le_fond_estimate",
        },
    },
    # experiment_bayes 最小效应量（与 experiment_bayes._min_effect 保持一致，可覆盖）
    "min_effect": {
        "shop_visit_to_pay_cvr": 0.005,
        "product_click_to_pay_cvr": 0.005,
        "inquiry_to_pay_cvr": 0.005,
        "repurchase_rate": 0.005,
        "refund_rate": 0.01,
        "aov": 10.0,
    },
    # stabilizer beta-binomial 先验强度（默认 8，可按行业调整）
    "beta_binomial_prior_strength": {
        "default": 8.0,
        "cold_start": 12.0,   # 样本少，更强先验
        "breakthrough": 5.0,   # 样本多，放弱先验
        "daily_ops": 4.0,
    },
    "version": CALIBRATION_VERSION,
}

# ── 加载流程 ─────────────────────────────────────────────────────────────────

_CALIBRATION_OVERRIDE_PATH = Path(__file__).resolve().parents[2] / "config" / "calibration" / "domain.yaml"
_loaded: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _loaded
    if _loaded is not None:
        return _loaded
    result = dict(_DEFAULT_CALIBRATION)
    if _CALIBRATION_OVERRIDE_PATH.exists():
        try:
            import yaml  # type: ignore[import]
            override = yaml.safe_load(_CALIBRATION_OVERRIDE_PATH.read_text(encoding="utf-8")) or {}
        except ModuleNotFoundError:
            # yaml 未安装时尝试 JSON（文件可以是 .yaml 名但 JSON 内容）
            try:
                override = json.loads(_CALIBRATION_OVERRIDE_PATH.read_text(encoding="utf-8"))
            except Exception:
                override = {}
        # Deep merge metric_priors
        if "metric_priors" in override:
            result.setdefault("metric_priors", {}).update(override["metric_priors"])
        for key in ("min_effect", "beta_binomial_prior_strength"):
            if key in override:
                result.setdefault(key, {}).update(override[key])
        if "version" in override:
            result["version"] = override["version"]
    _loaded = result
    return result


# ── 公开 API ─────────────────────────────────────────────────────────────────

def calibration_ref(component: str) -> str:
    """生成校准引用字符串，用于 artifact 溯源。"""
    version = _load().get("version", CALIBRATION_VERSION)
    return f"calibration__{component}__{version}"


def get_prior(metric_name: str) -> dict[str, Any]:
    """
    返回某指标的先验参数：
    {
        pool_mean: float | None,
        prior_strength: float,
        note: str,
    }
    """
    cal = _load()
    priors = cal.get("metric_priors", {})
    default_prior = {"pool_mean": None, "prior_strength": 6.0, "note": "default_fallback"}
    return priors.get(metric_name, default_prior)


def get_min_effect(metric_name: str) -> float:
    """
    返回某指标的最小有实际意义效应量（MDE）。
    优先使用校准文件，fallback 到 experiment_bayes 内置值。
    """
    cal = _load()
    me = cal.get("min_effect", {})
    if metric_name in me:
        return float(me[metric_name])
    # fallback 到 experiment_bayes 的内置逻辑
    if metric_name in {"shop_visit_to_pay_cvr", "product_click_to_pay_cvr",
                       "inquiry_to_pay_cvr", "repurchase_rate"}:
        return 0.005
    if metric_name == "refund_rate":
        return 0.01
    if metric_name == "aov":
        return 10.0
    return 1.0


def get_prior_strength_for_stage(stage: str) -> float:
    """
    根据经营阶段返回 beta-binomial 先验强度。
    stage 越早 → 先验越强（样本少，需要更多信念保护）。
    """
    cal = _load()
    bb = cal.get("beta_binomial_prior_strength", {})
    return float(bb.get(stage, bb.get("default", 8.0)))


def all_calibration() -> dict[str, Any]:
    """返回完整校准参数（调试/文档用）。"""
    return dict(_load())


def reload() -> None:
    """强制重新加载校准文件（测试/热更新用）。"""
    global _loaded
    _loaded = None
    _load()
