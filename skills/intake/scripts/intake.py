#!/usr/bin/env python3
"""
/intake — 品牌问卷，生成 brand_profile.yaml
"""
from __future__ import annotations
import sys, yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from revenue_os.normalization.profile_builder import generate_brand_profile

PROFILE_PATH = ROOT / "brand_profile.yaml"

# ── 选项定义 ─────────────────────────────────────────────────────────────────
ROLES = [("merchant","商家（有小红书店铺）"),("blogger","博主（以内容涨粉为主）"),
         ("brand","品牌方（旗舰店）"),("lead_gen","获客型（私域/线下引流）")]
BUSINESS_MODELS = [("ecommerce","图文挂购物车"),("store_live","店铺直播"),
                   ("content","纯内容种草"),("search","搜索推广"),("private_domain","私域转化")]
INDUSTRIES = ["服饰","珠宝配饰","美妆","食品饮料","母婴","家居家装","大健康",
              "教育","生活服务","宠物","3C家电","通用（其他）"]
STAGES = [("cold_start","冷启动（<3个月/粉丝<1K）"),("ramp_up","爬坡期（3-12个月）"),
          ("breakthrough","突破期（有过爆款/粉丝5K+）"),("burst","爆发期（粉丝50K+）"),
          ("daily_ops","日常运营（稳定出单）"),("campaign","大促冲刺")]
OBJECTIVES = [("conversion","提升转化率"),("gmv","提GMV"),("followers_growth","涨粉"),
              ("exposure","曝光破圈"),("repurchase","提复购"),("roi","提ROI"),
              ("store_visit","增加进店流量"),("lead_capture","获客留资")]
PAIN_OPTS = [("no_traffic","没流量"),("traffic_no_conversion","有流量没转化"),
             ("low_aov","客单价低"),("no_repurchase","粉丝不复购"),
             ("search_invisible","搜索找不到我"),("content_stuck","不知道发什么内容")]


def _ask(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        sys.exit(0)


def _choose(options: list[tuple[str, str]], prompt: str, multi: bool = False, max_n: int = 2) -> str | list[str]:
    print(f"\n{prompt}")
    for i, (val, label) in enumerate(options, 1):
        print(f"  {i}. {label}")
    hint = f"输入数字（多选用逗号分隔，最多{max_n}个）" if multi else "输入数字"
    while True:
        raw = _ask(f"{hint}: ")
        idxs = [s.strip() for s in raw.split(",")]
        try:
            chosen = [options[int(i) - 1][0] for i in idxs if i]
            if multi:
                chosen = chosen[:max_n]
                return chosen if chosen else [options[0][0]]
            return chosen[0] if chosen else options[0][0]
        except (ValueError, IndexError):
            print("  请输入有效数字。")


def _ask_float(prompt: str) -> float | None:
    raw = _ask(prompt + "（回车跳过）: ")
    if not raw:
        return None
    try:
        return float(raw.replace("%", "").strip())
    except ValueError:
        return None


def run_intake() -> None:
    print("\n" + "="*55)
    print("  Revenue OS /intake — 品牌配置（约5分钟）")
    print("="*55)

    responses: dict = {}

    # ── Section 1：账号基本面（必填）────────────────────────────────────────
    print("\n【Section 1 / 3】账号基本面")
    responses["role"] = _choose(ROLES, "你的角色是？")
    responses["business_model"] = _choose(BUSINESS_MODELS, "主要变现方式？（可多选2个）", multi=True, max_n=2)
    print("\n所属行业？")
    for i, ind in enumerate(INDUSTRIES, 1):
        print(f"  {i}. {ind}")
    while True:
        raw = _ask("输入数字: ")
        try:
            ind = INDUSTRIES[int(raw) - 1]
            responses["industry"] = "通用" if "通用" in ind else ind
            break
        except (ValueError, IndexError):
            print("  请输入有效数字。")
    responses["stage"] = _choose(STAGES, "账号当前阶段？")
    age_raw = _ask("\n账号开通多久了？（月，回车跳过）: ")
    responses["account_age_months"] = int(age_raw) if age_raw.isdigit() else None

    # ── Section 2：核心指标（可跳过）────────────────────────────────────────
    print("\n【Section 2 / 3】核心指标")
    print("填你能查到的数据，不确定的直接回车跳过。")
    print("提示：运行 `opencli xiaohongshu creator-stats -f json > data/creator_stats.json` 可自动获取部分数据\n")
    skip2 = _ask("跳过本 Section？(y/回车继续): ").lower()
    if skip2 != "y":
        responses["recent_note_median_views"] = _ask_float("近30天笔记中位曝光（次）")
        responses["cover_ctr"]               = _ask_float("封面点击率 % （行业均值约5%）")
        responses["engagement_rate"]         = _ask_float("互动率 % （点赞+收藏+评论/曝光，均值约4%）")
        if "store_live" in responses.get("business_model", []):
            responses["completion_rate"]     = _ask_float("视频完播率 %")
        responses["search_ctr"]             = _ask_float("搜索点击率 % （千帆后台→搜索分析）")
        if responses["role"] in ["merchant", "brand"]:
            responses["shop_visit_to_pay_cvr"]     = _ask_float("进店→购买转化率 %")
            responses["product_click_to_pay_cvr"]  = _ask_float("商品点击→购买转化率 %")
        responses["aov"]            = _ask_float("客单价（元）")
        responses["repurchase_rate"] = _ask_float("30天复购率 %")
        responses["recent_note_count_30d"] = _ask_float("近30天发布笔记数")

    # ── Section 3：目标与约束（可跳过）──────────────────────────────────────
    print("\n【Section 3 / 3】目标与约束")
    skip3 = _ask("跳过本 Section？(y/回车继续): ").lower()
    if skip3 != "y":
        responses["primary_objective"] = _choose(OBJECTIVES, "当前最重要的目标？")
        gmv_raw = _ask("\n月GMV目标（元，回车跳过）: ")
        responses["monthly_gmv_target"] = float(gmv_raw) if gmv_raw.replace(".","").isdigit() else None
        cap = _ask("每周能产出多少内容？(1) 1-2条  (2) 3-5条  (3) 每天1条+  [默认2]: ") or "2"
        responses["content_capacity"] = {"1":"1-2/week","2":"3-5/week","3":"daily"}.get(cap,"3-5/week")
        live_raw = _ask("是否已开通直播？(y/n，默认n): ").lower()
        responses["has_live"] = live_raw == "y"
        responses["pain_points"] = _choose(PAIN_OPTS, "当前最大的痛点？（可多选2个）", multi=True, max_n=2)

    # ── 生成 brand_profile.yaml ──────────────────────────────────────────────
    profile = generate_brand_profile(responses)
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        yaml.dump(profile, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    print("\n" + "="*55)
    print(f"✅ brand_profile.yaml 已生成：{PROFILE_PATH}")
    print(f"   行业：{profile['industry']}  阶段：{profile['stage']}")
    print(f"   主要目标：{profile.get('primary_objective','conversion')}")
    print(f"   推断主任务：{profile['inferred']['primary_mission']}")
    print("\n下一步：运行 /diagnose 获取账号诊断报告")
    print("="*55)


if __name__ == "__main__":
    run_intake()
