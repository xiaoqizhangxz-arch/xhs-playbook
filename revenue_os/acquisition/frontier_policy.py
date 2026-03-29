from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from revenue_os.acquisition.creator_catalog import get_creator_surface, is_creator_surface_proven
from revenue_os.acquisition.surface_catalog import get_surface, is_qianfan_surface_proven


FRONTIER_POLICY: dict[str, dict[str, str | None]] = {
    "/api/edith/seller/info/v2": {"decision": "monitor", "category": "merchant_identity", "usage": "店铺主体信息/权限上下文", "mapped_surface_name": "business_summary"},
    "/api/edith/home/get_shop_score": {"decision": "promote_p1", "category": "merchant_health", "usage": "店铺分/经营健康分", "mapped_surface_name": "business_summary"},
    "/edith/api/seller/common/query_hit_gray": {"decision": "monitor", "category": "feature_flag", "usage": "灰度开关命中查询", "mapped_surface_name": None},
    "/api/edith/bench/sidebar": {"decision": "monitor", "category": "ui_nav", "usage": "工作台侧栏配置/入口可见性", "mapped_surface_name": None},
    "/api/edith/seller/vender/info": {"decision": "monitor", "category": "merchant_identity", "usage": "商家主体与资质基础信息", "mapped_surface_name": "business_summary"},
    "/fe_api/burdock/v2/shield/profile": {"decision": "ignore_for_planner", "category": "risk_control", "usage": "风控/安全画像", "mapped_surface_name": None},
    "/api/edith/mkt/is_white_seller": {"decision": "monitor", "category": "eligibility", "usage": "营销白名单资格", "mapped_surface_name": "marketing_tool"},
    "/api/rocking/tob/resource/plan/batch/get": {"decision": "monitor", "category": "marketing_resource", "usage": "营销资源位/计划批量查询", "mapped_surface_name": "marketing_tool"},
    "/api/edith/open/message/v2/unread-count": {"decision": "ignore_for_planner", "category": "message_center", "usage": "未读消息数", "mapped_surface_name": None},
    "/api/edith/message/query_pop_window": {"decision": "ignore_for_planner", "category": "message_center", "usage": "弹窗消息配置", "mapped_surface_name": None},
    "/api/edith/bench/topbar": {"decision": "monitor", "category": "ui_nav", "usage": "顶栏配置/入口信息", "mapped_surface_name": None},
    "/api/edith/cs/fe/apollo": {"decision": "monitor", "category": "customer_service_cfg", "usage": "客服端配置下发", "mapped_surface_name": "customer_data"},
    "/api/edith/cs/check_help_cs": {"decision": "monitor", "category": "customer_service_cfg", "usage": "客服能力/连通性校验", "mapped_surface_name": "customer_data"},
    "/api/edith/butterfly/data": {"decision": "monitor", "category": "ops_recommendation", "usage": "运营推荐位/引导数据", "mapped_surface_name": None},
    "/api/edith/search/pagekeyword": {"decision": "promote_p0", "category": "search_data", "usage": "搜索关键词分页明细", "mapped_surface_name": "search_terms"},
    "/api/edith/business/data/slogan": {"decision": "ignore_for_planner", "category": "ui_copy", "usage": "经营页文案/口号配置", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/89": {"decision": "monitor", "category": "app_slot_cfg", "usage": "功能应用位配置(89)", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/64": {"decision": "monitor", "category": "app_slot_cfg", "usage": "功能应用位配置(64)", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/63": {"decision": "monitor", "category": "app_slot_cfg", "usage": "功能应用位配置(63)", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/254": {"decision": "monitor", "category": "app_slot_cfg", "usage": "功能应用位配置(254)", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/41": {"decision": "monitor", "category": "app_slot_cfg", "usage": "功能应用位配置(41)", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/74": {"decision": "monitor", "category": "app_slot_cfg", "usage": "功能应用位配置(74)", "mapped_surface_name": None},
    "/api/edith/business_data/metric_dictionary/batchsearch": {"decision": "promote_p1", "category": "metric_dictionary", "usage": "指标字典定义查询", "mapped_surface_name": "datacenter_overview"},
    "/api/edith/business_data/item/catagory": {"decision": "promote_p1", "category": "category_analysis", "usage": "商品类目经营数据", "mapped_surface_name": "category_analysis"},
    "/api/edith/business/data/note/rank/v2/list": {"decision": "promote_p1", "category": "market_benchmark", "usage": "市场笔记排行列表", "mapped_surface_name": "market_note_rank"},
    "/api/edith/business/data/live/tops/filter": {"decision": "promote_p2", "category": "market_benchmark", "usage": "市场直播排行筛选项", "mapped_surface_name": "market_live_rank"},
    "/api/edith/business/data/top/live/data/search": {"decision": "promote_p2", "category": "market_benchmark", "usage": "市场直播排行搜索", "mapped_surface_name": "market_live_rank"},
    "/api/edith/business/data/top/live/self/data": {"decision": "promote_p2", "category": "market_benchmark", "usage": "市场直播排行自营数据", "mapped_surface_name": "market_live_rank"},
    "/api/edith/business_data/seller/core/page/flow": {"decision": "promote_p0", "category": "shop_funnel", "usage": "店铺页核心流转漏斗", "mapped_surface_name": "shop_funnel"},
    "/api/edith/business_data/seller/page/source/advice": {"decision": "promote_p1", "category": "shop_funnel", "usage": "店铺来源建议/流量来源建议", "mapped_surface_name": "shop_entry_source"},
    "/api/edith/v1/electronic_bill/switchgray": {"decision": "monitor", "category": "fulfillment_cfg", "usage": "电子面单灰度开关", "mapped_surface_name": "dispatching_center"},
    "/api/edith/address/gray": {"decision": "monitor", "category": "fulfillment_cfg", "usage": "地址能力灰度开关", "mapped_surface_name": "dispatching_center"},
    "/api/suez/common/getSellerId": {"decision": "monitor", "category": "merchant_identity", "usage": "商家ID映射", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/trigger": {"decision": "monitor", "category": "app_slot_cfg", "usage": "应用触发器/埋点触发", "mapped_surface_name": None},
    "/api/edith/governance/traction/query_seller_category_amount_details": {"decision": "promote_p1", "category": "governance_finance", "usage": "类目保证金/治理金额明细", "mapped_surface_name": "deposit_category_base"},
    "/api/edith/crm/user_crowd_asset_config_v2": {"decision": "promote_p1", "category": "crm_crowd", "usage": "人群资产配置", "mapped_surface_name": "aipl_assets"},
    "/api/edith/crm/user_crowd_scene_detail": {"decision": "promote_p1", "category": "crm_crowd", "usage": "人群场景明细", "mapped_surface_name": "aipl_assets"},
    "/api/edith/crm/user_crowd_content_detail": {"decision": "promote_p1", "category": "crm_crowd", "usage": "人群内容偏好明细", "mapped_surface_name": "aipl_assets"},
    "/api/edith/seller/deliverygroup": {"decision": "promote_p1", "category": "fulfillment", "usage": "发货分组信息", "mapped_surface_name": "dispatching_center"},
    "/api/edith/logistics/service/product/list/query": {"decision": "promote_p1", "category": "fulfillment", "usage": "物流服务产品列表", "mapped_surface_name": "logistics_data"},
    "/api/edith/fulfillment/apolloconfig": {"decision": "monitor", "category": "fulfillment_cfg", "usage": "履约配置项", "mapped_surface_name": "dispatching_center"},
    "/api/edith/fulfillment/delivery/record/detail": {"decision": "promote_p1", "category": "fulfillment", "usage": "发货记录详情", "mapped_surface_name": "dispatching_center"},
    "/api/edith/after-sales/gray/config/get_by_scene_keys": {"decision": "monitor", "category": "after_sale_cfg", "usage": "售后灰度配置", "mapped_surface_name": "aftersale_manage"},
    "/api/edith/after-sales/gray_merchant/query": {"decision": "monitor", "category": "after_sale_cfg", "usage": "商家售后灰度状态", "mapped_surface_name": "aftersale_manage"},
    "/api/edith/logistics/delivery_services/subscribed_cp_list": {"decision": "promote_p1", "category": "fulfillment", "usage": "订阅物流承运商列表", "mapped_surface_name": "logistics_data"},
    "/api/edith/after-sales/returns/return-reasons/v1": {"decision": "promote_p1", "category": "after_sale", "usage": "退货原因字典", "mapped_surface_name": "after_sale_data"},
    "/api/edith/after-sales/merchant_data_abnormal_standard": {"decision": "promote_p1", "category": "after_sale", "usage": "售后异常判定标准", "mapped_surface_name": "after_sale_data"},
    "/api/edith/after-sales/merchant_data_diagnosis": {"decision": "promote_p0", "category": "after_sale", "usage": "售后诊断结果", "mapped_surface_name": "after_sale_data"},
    "/api/edith/after-sales/returns/v3": {"decision": "promote_p0", "category": "after_sale", "usage": "退货/退款单据明细", "mapped_surface_name": "aftersale_manage"},
    "/api/edith/after-sales/home/popup": {"decision": "monitor", "category": "after_sale_ui", "usage": "售后首页弹窗", "mapped_surface_name": "after_sale_data"},
    "/api/edith/after-sales/home/banner": {"decision": "monitor", "category": "after_sale_ui", "usage": "售后首页banner", "mapped_surface_name": "after_sale_data"},
    "/api/suez/finance/accountforweb/getAggregateAccount": {"decision": "promote_p1", "category": "settlement_finance", "usage": "资金账户汇总", "mapped_surface_name": "settlement_funds"},
    "/api/suez/finance/accountforweb/topTips": {"decision": "monitor", "category": "settlement_finance", "usage": "资金页提示信息", "mapped_surface_name": "settlement_funds"},
    "/api/suez/finance/accountforweb/erqingSwtichInfo": {"decision": "monitor", "category": "settlement_finance", "usage": "资金/二清开关状态", "mapped_surface_name": "settlement_funds"},
    "/api/suez/finance/accountforweb/listAccountRecord": {"decision": "promote_p1", "category": "settlement_finance", "usage": "资金流水记录", "mapped_surface_name": "settlement_funds"},
    "/api/robin/application/627": {"decision": "monitor", "category": "app_slot_cfg", "usage": "应用位配置(627)", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/70": {"decision": "monitor", "category": "app_slot_cfg", "usage": "应用位配置(70)", "mapped_surface_name": None},
    "/api/edith/settlebill/query_store_info": {"decision": "promote_p1", "category": "settlement_finance", "usage": "结算店铺信息", "mapped_surface_name": "settlement_funds"},
    "/api/suez/finance/accountforweb/getWechatRegistRedirectPath": {"decision": "monitor", "category": "settlement_finance", "usage": "微信签约跳转路径", "mapped_surface_name": "settlement_funds"},
    "/api/suez/sellerstatementservice/ark/tosettle/account": {"decision": "promote_p1", "category": "settlement_finance", "usage": "待结算账户汇总", "mapped_surface_name": "pending_settle_orders"},
    "/api/suez/sellerstatementservice/ark/tosettle/order/page": {"decision": "promote_p1", "category": "settlement_finance", "usage": "待结算订单分页", "mapped_surface_name": "pending_settle_orders"},
    "/api/robin/application/623": {"decision": "monitor", "category": "app_slot_cfg", "usage": "应用位配置(623)", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/71": {"decision": "monitor", "category": "app_slot_cfg", "usage": "应用位配置(71)", "mapped_surface_name": None},
    "/api/edith/product/search_item_v2": {"decision": "promote_p1", "category": "product_ops", "usage": "商品搜索/列表", "mapped_surface_name": "shelf_goods"},
    "/api/edith/product/query_seller_high_price_info": {"decision": "monitor", "category": "product_ops", "usage": "高价商品信息", "mapped_surface_name": "shelf_goods"},
    "/api/edith/product/check_freeze": {"decision": "promote_p1", "category": "product_ops", "usage": "商品冻结状态检查", "mapped_surface_name": "shelf_goods"},
    "/api/edith/product/get_logistics_info": {"decision": "promote_p1", "category": "product_ops", "usage": "商品物流配置", "mapped_surface_name": "shelf_goods"},
    "/api/edith/product/get_delivery_time_rule": {"decision": "promote_p1", "category": "product_ops", "usage": "发货时效规则", "mapped_surface_name": "shelf_goods"},
    "/api/edith/product/seller_item_count": {"decision": "promote_p1", "category": "product_ops", "usage": "在售商品计数", "mapped_surface_name": "shelf_goods"},
    "/api/edith/inventory/gray_config": {"decision": "monitor", "category": "inventory_cfg", "usage": "库存灰度配置", "mapped_surface_name": "shelf_goods"},
    "/api/edith/product/get_common_config": {"decision": "monitor", "category": "product_ops_cfg", "usage": "商品公共配置", "mapped_surface_name": "shelf_goods"},
    "/api/edith/seller/get_seller_info": {"decision": "monitor", "category": "merchant_identity", "usage": "商家信息补充", "mapped_surface_name": "business_summary"},
    "/api/edith/product/seller_property_hosting_status": {"decision": "monitor", "category": "product_ops", "usage": "商品托管属性状态", "mapped_surface_name": "shelf_goods"},
    "/api/edith/product/stock/getout_of_inventory_item": {"decision": "promote_p1", "category": "inventory_ops", "usage": "缺货商品列表", "mapped_surface_name": "shelf_goods"},
    "/api/edith/redbreast/api/toc/robin/application/253": {"decision": "monitor", "category": "app_slot_cfg", "usage": "应用位配置(253)", "mapped_surface_name": None},
    "/api/edith/business_data/realtime_overview_v2": {"decision": "promote_p0", "category": "realtime_business", "usage": "实时经营总览", "mapped_surface_name": "good_data_realtime"},
    "/api/edith/business_data/realtime_trend_v2": {"decision": "promote_p0", "category": "realtime_business", "usage": "实时经营趋势", "mapped_surface_name": "good_data_realtime"},
    "/api/edith/business_data/realtime_item_v2": {"decision": "promote_p1", "category": "realtime_business", "usage": "实时商品明细数据", "mapped_surface_name": "good_data_realtime"},
    "/api/edith/recommend/data": {"decision": "monitor", "category": "ops_recommendation", "usage": "系统推荐数据", "mapped_surface_name": None},
    "/api/edith/redbreast/api/toc/robin/application/62": {"decision": "monitor", "category": "app_slot_cfg", "usage": "应用位配置(62)", "mapped_surface_name": None},
    "/api/edith/business_data/goods_note/category/list": {"decision": "promote_p1", "category": "content_commerce", "usage": "商品笔记类目列表", "mapped_surface_name": "product_note_data"},
    "/api/edith/crm/crowd_v2": {"decision": "promote_p1", "category": "crm_crowd", "usage": "成交分析人群漏斗(认知-意向-新客-老客-流失)", "mapped_surface_name": "aipl_assets"},
    "/api/edith/open/message/v2/important-msgs": {"decision": "ignore_for_planner", "category": "message_center", "usage": "重要消息列表", "mapped_surface_name": None},
    "/api/edith/open/message/latest_group_mgs": {"decision": "ignore_for_planner", "category": "message_center", "usage": "群消息摘要", "mapped_surface_name": None},
    "/api/edith/juliet/uno/get_menu_tree": {"decision": "monitor", "category": "ui_nav", "usage": "菜单树配置", "mapped_surface_name": None},
    "/edith/api/seller/query_merchant_apply_status": {"decision": "monitor", "category": "merchant_identity", "usage": "商家入驻/申请状态", "mapped_surface_name": "business_summary"},
    "/edith/api/seller/home/key_metric_realtime": {"decision": "promote_p1", "category": "merchant_health", "usage": "商家首页实时关键指标", "mapped_surface_name": "datacenter_overview"},
    "/edith/api/seller/todolist": {"decision": "monitor", "category": "merchant_ops", "usage": "商家待办事项", "mapped_surface_name": None},
    "/api/edith/seller/query_management_advice": {"decision": "monitor", "category": "merchant_ops", "usage": "经营建议列表", "mapped_surface_name": None},
    "/api/edith/query/selleram/info": {"decision": "monitor", "category": "merchant_identity", "usage": "商家账户经理信息", "mapped_surface_name": None},
    "/edith/api/seller/get_homepage_banner_activities": {"decision": "monitor", "category": "merchant_ops", "usage": "首页活动 banner 信息", "mapped_surface_name": None},
    "/api/edith/deliver/resource/data": {"decision": "promote_p1", "category": "fulfillment", "usage": "发货资源/承运资源数据", "mapped_surface_name": "dispatching_center"},
    "/api/galaxy/creator/select/topic/detail": {"decision": "promote_p2", "category": "creator_topic", "usage": "创作话题详情/灵感池", "mapped_surface_name": "creator_inspiration"},
    "/api/galaxy/creator/user/video": {"decision": "promote_p1", "category": "creator_content", "usage": "作者视频资产/作品视频数据", "mapped_surface_name": "creator_note_manager"},
    "/api/galaxy/creator/home/personal_info": {"decision": "promote_p1", "category": "creator_profile", "usage": "创作者主页个人信息/KPI概览", "mapped_surface_name": "creator_home"},
    "/api/galaxy/v2/creator/portal/authortask": {"decision": "promote_p2", "category": "creator_task", "usage": "作者任务/活动任务", "mapped_surface_name": "creator_events"},
    "/api/galaxy/creator/datacenter/note/base": {"decision": "promote_p0", "category": "creator_content", "usage": "笔记数据基础指标", "mapped_surface_name": "creator_note_manager"},
}


def classify_endpoint(endpoint: str, source_system: str) -> dict[str, Any]:
    path = urlparse(endpoint).path
    policy = FRONTIER_POLICY.get(path)
    if not policy:
        return {
            "decision": "unknown",
            "category": "unknown",
            "usage": "待人工确认",
            "mapped_surface_name": None,
            "integration_status": "unmapped",
        }

    mapped = str(policy.get("mapped_surface_name") or "")
    if not mapped:
        integration_status = "unmapped"
    elif source_system == "qianfan":
        try:
            spec = get_surface(mapped)
            integration_status = "integrated_proven" if is_qianfan_surface_proven(spec) else "planned_in_catalog"
        except Exception:
            integration_status = "unmapped"
    else:
        try:
            spec = get_creator_surface(mapped)
            integration_status = "integrated_proven" if is_creator_surface_proven(spec) else "planned_in_catalog"
        except Exception:
            integration_status = "unmapped"

    return {
        "decision": policy["decision"],
        "category": policy["category"],
        "usage": policy["usage"],
        "mapped_surface_name": policy["mapped_surface_name"],
        "integration_status": integration_status,
    }
