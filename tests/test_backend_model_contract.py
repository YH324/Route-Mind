import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_service import CITY_CENTERS, run_agent
from interaction_intelligence import LOCATION_ALIASES
from route_planner_v3 import (
    classify_intent_with_llm,
    _INTENT_LLM_UNAVAILABLE_UNTIL,
    _correct_candidate_type,
    _estimated_review_signal,
    _route_feasibility_policy,
    _segment_route_feasible,
    _score_poi_features,
)


class TestBackendModelContract(unittest.TestCase):
    def test_tianfu_square_coordinates_are_central_chengdu(self):
        expected_lng = 104.06476
        expected_lat = 30.65705
        for source in (CITY_CENTERS["chengdu"], CITY_CENTERS["tianfu"], LOCATION_ALIASES["天府广场"]):
            self.assertAlmostEqual(source["lng"], expected_lng, places=4)
            self.assertAlmostEqual(source["lat"], expected_lat, places=4)

    def test_unsupported_service_area_is_rejected_before_planning(self):
        for goal in ("广州塔附近吃晚饭", "重庆解放碑附近喝咖啡", "青羊区宽窄巷子半日游"):
            response = run_agent(
                {"goal": goal, "city": "chengdu", "radius": 3000, "user_mode": "tourist"},
                request_id="unsupported-area-contract-test",
            )
            self.assertFalse(response["ok"], response)
            self.assertEqual(response["error_code"], "UNSUPPORTED_SERVICE_AREA")
            self.assertEqual(response["service_area"]["districts"], ["武侯区", "锦江区"])

    def test_explicit_location_outside_service_area_is_rejected(self):
        response = run_agent(
            {
                "goal": "附近吃火锅",
                "city": "chengdu",
                "center_lng": 113.319,
                "center_lat": 23.109,
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="unsupported-location-contract-test",
        )
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error_code"], "UNSUPPORTED_SERVICE_AREA")
        self.assertIn("bounds", response["service_area"])

    def test_ambiguous_short_goal_returns_clarification_options(self):
        response = run_agent(
            {
                "goal": "随便安排一下",
                "city": "taikooli",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="clarification-contract-test",
        )
        self.assertTrue(response["ok"], response)
        self.assertFalse(response["result"]["variants"])
        self.assertEqual(response["result"]["constraints"].get("intent_type"), "clarification")
        options = response.get("clarification_options")
        self.assertTrue(options, response)
        self.assertTrue(all("太古里" in option.get("goal", "") for option in options), options)
        self.assertIn("需要", response.get("notice", ""))

    def test_local_landmark_mentions_recenter_request(self):
        response = run_agent(
            {
                "goal": "锦里附近吃小吃，再去武侯祠周边逛逛",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="local-landmark-contract-test",
        )
        self.assertTrue(response["ok"], response)
        center = response["result"]["center"]
        self.assertEqual(center["center_key"], "jinli")
        self.assertAlmostEqual(center["lng"], CITY_CENTERS["jinli"]["lng"], places=4)
        self.assertAlmostEqual(center["lat"], CITY_CENTERS["jinli"]["lat"], places=4)

    def test_plan_response_contains_model_trace_and_recommendation_basis(self):
        response = run_agent(
            {
                "goal": "天府广场附近想吃火锅",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="model-contract-test",
        )
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertIn("model", result)
        self.assertIn("candidate_pipeline", result["model"])
        self.assertGreater(result["model"]["candidate_pipeline"]["raw_poi_count"], 0)
        self.assertGreaterEqual(result["model"]["candidate_pipeline"]["candidate_pool_after_cap"], 0)

        self.assertTrue(result["variants"], result)
        first_variant = result["variants"][0]
        items = first_variant.get("route") or first_variant.get("recommendations") or []
        self.assertTrue(items, first_variant)
        basis = items[0].get("recommendation_basis")
        self.assertIsInstance(basis, dict)
        self.assertIn("top_reasons", basis)
        self.assertTrue(basis["top_reasons"])
        self.assertIn("features", basis)
        self.assertIn("quality_score", basis["features"])
        self.assertIn("review_count_estimate", basis["features"])
        self.assertIn("popularity_adjustment", basis["features"])
        self.assertIn("open_at_arrival", basis["features"])
        self.assertIn("estimated_review_volume", result["model"]["feature_sources"])
        self.assertNotEqual(result["model"]["intent"].get("provider"), "fallback")

    def test_configured_llm_is_tried_before_local_intent_gate(self):
        with patch("route_planner_v3.MIMO_API_KEY", "test-key"), \
             patch("route_planner_v3.MINIMAX_API_KEY", ""), \
             patch("route_planner_v3.GLM_API_KEY", ""), \
             patch.dict(_INTENT_LLM_UNAVAILABLE_UNTIL, {}, clear=True), \
             patch("route_planner_v3._call_llm_api") as call_llm:
            call_llm.return_value = {
                "intent_type": "single_poi",
                "reason": "用户只想找附近火锅",
            }

            result = classify_intent_with_llm("春熙路附近想吃火锅")

        self.assertTrue(call_llm.called)
        self.assertEqual(result["intent_type"], "single_poi")
        self.assertTrue(result["llm_used"])
        self.assertEqual(result["provider"], "mimo")

    def test_failed_intent_llm_uses_cooldown_before_local_fallback(self):
        with patch("route_planner_v3.MIMO_API_KEY", "test-key"), \
             patch("route_planner_v3.MINIMAX_API_KEY", ""), \
             patch("route_planner_v3.GLM_API_KEY", ""), \
             patch("route_planner_v3.INTENT_LLM_FAILURE_COOLDOWN_SECONDS", 60), \
             patch.dict(_INTENT_LLM_UNAVAILABLE_UNTIL, {}, clear=True), \
             patch("route_planner_v3._call_llm_api", side_effect=OSError("down")) as call_llm:
            first = classify_intent_with_llm("春熙路附近想吃火锅")
            second = classify_intent_with_llm("春熙路附近想吃火锅")

        self.assertEqual(call_llm.call_count, 1)
        self.assertEqual(first["provider"], "deterministic_gate")
        self.assertEqual(second["provider"], "deterministic_gate")
        self.assertIn("temporarily skipped", second.get("llm_error", ""))

    def test_explicit_park_single_poi_does_not_expand_to_all_sights(self):
        response = run_agent(
            {
                "goal": "天府广场附近去公园",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="park-contract-test",
        )
        self.assertTrue(response["ok"], response)
        recs = response["result"]["variants"][0].get("recommendations", [])
        self.assertTrue(recs)
        for rec in recs:
            self.assertEqual(rec["type"], "公园", rec)
            self.assertNotIn("门", rec["name"], rec)
            self.assertFalse(any(term in rec["name"] for term in ("超市", "商品", "直销", "酒业", "旧址")), rec)

    def test_entity_type_correction_rejects_known_false_positives(self):
        greenland_supermarket = {
            "poi_id": "park-false-positive",
            "name": "G-Super绿地超市(来福士店)",
            "type": "购物服务;超级市场;超市",
            "typecode": "060400",
            "tags": ["家电数码"],
            "grid_density": 121,
            "nearest_same_type_m": 0,
            "longitude": 104.06476,
            "latitude": 30.65705,
        }
        event_venue = {
            "poi_id": "restaurant-false-positive",
            "name": "西博会",
            "type": "餐饮服务;餐饮相关场所;餐饮相关",
            "typecode": "050000",
            "tags": ["餐饮"],
            "grid_density": 68,
            "nearest_same_type_m": 0,
            "longitude": 104.06476,
            "latitude": 30.65705,
        }
        hotel = {
            "poi_id": "hotel-false-positive",
            "name": "明宇丽雅饭店",
            "type": "住宿服务;宾馆酒店;五星级宾馆",
            "typecode": "100102",
            "tags": ["住宿"],
            "grid_density": 482,
            "nearest_same_type_m": 0,
            "longitude": 104.06476,
            "latitude": 30.65705,
        }
        self.assertEqual(_correct_candidate_type(greenland_supermarket, "公园"), "超市")
        self.assertEqual(_correct_candidate_type(event_venue, "中餐"), "其他")
        self.assertEqual(_correct_candidate_type(hotel, "中餐"), "住宿")

    def test_general_shopping_service_is_not_promoted_to_supermarket(self):
        luxury_store = {
            "poi_id": "luxury-shopping-not-supermarket",
            "name": "SAINT LAURENT PARIS",
            "type": "购物服务;服装鞋帽皮具店;品牌服装店",
            "typecode": "061101",
            "tags": ["购物"],
            "grid_density": 180,
            "nearest_same_type_m": 0,
            "longitude": 104.06476,
            "latitude": 30.65705,
        }
        self.assertEqual(_correct_candidate_type(luxury_store, "购物"), "购物")

    def test_popularity_signal_uses_type_density_and_quality(self):
        poi = {
            "poi_id": "heat-sample",
            "name": "样例火锅",
            "type": "餐饮服务;火锅店;火锅店",
            "grid_density": 300,
            "nearest_same_type_m": 20,
            "longitude": 104.06476,
            "latitude": 30.65705,
        }
        low_count, low_adj, _ = _estimated_review_signal(poi, "火锅", 3.0)
        high_count, high_adj, _ = _estimated_review_signal(poi, "火锅", 4.5)
        self.assertGreater(high_count, low_count)
        self.assertGreater(high_adj, low_adj)
        score, features, reasons, real_type = _score_poi_features(
            poi, {"overall": 4.5}, {"preferred_tags": ["火锅"], "user_mode_label": "游客"}, set(), None, None
        )
        self.assertEqual(real_type, "火锅")
        self.assertGreater(score, 0)
        self.assertGreater(features["review_count_estimate"], 0)
        self.assertGreater(features["popularity_adjustment"], 0)
        self.assertTrue(any("评价热度" in reason for reason in reasons))

    def test_closed_or_under_renovation_pois_are_filtered(self):
        response = run_agent(
            {
                "goal": "想吃火锅",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="status-filter-contract-test",
        )
        self.assertTrue(response["ok"], response)
        recs = response["result"]["variants"][0].get("recommendations", [])
        self.assertTrue(recs)
        bad_terms = ("暂停营业", "装修中", "已关闭", "停业", "歇业")
        for rec in recs:
            self.assertFalse(any(term in rec["name"] for term in bad_terms), rec)

    def test_chunxi_hotpot_prioritizes_recognizable_full_service_brands(self):
        response = run_agent(
            {
                "goal": "春熙路附近想吃火锅",
                "city": "chengdu",
                "center_lng": 104.08099,
                "center_lat": 30.65732,
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="hotpot-brand-contract-test",
        )
        self.assertTrue(response["ok"], response)
        model = response["result"]["model"]
        self.assertEqual(model["ranking_model"], "feature_ranker_v1.5")
        self.assertEqual(response["result"]["constraints"].get("time_budget_hours"), 1.5)
        self.assertEqual(response["result"]["constraints"].get("time_budget_source"), "inferred")
        self.assertIn("data_driven_brand_recognition", model["feature_sources"])
        self.assertIn("entity_fit_quality", model["feature_sources"])
        self.assertIn("llm_candidate_review", model["candidate_pipeline"])
        recs = response["result"]["variants"][0].get("recommendations", [])
        self.assertGreaterEqual(len(recs), 3)
        top_names = [rec["name"] for rec in recs[:5]]
        famous_terms = ("海底捞", "小龙坎", "大龙燚", "老码头", "谭鸭血", "袁老四", "楠火锅", "集渔", "大妙", "吼堂")
        self.assertTrue(any(any(term in name for term in famous_terms) for name in top_names), top_names)
        weak_terms = ("充电", "街电", "怪兽", "麻辣烫", "冒菜", "甜品", "冷饮")
        self.assertFalse(any(any(term in name for term in weak_terms) for name in top_names[:3]), top_names)
        brands = [rec["recommendation_basis"]["features"].get("matched_brand") or rec["name"] for rec in recs[:5]]
        self.assertEqual(len(brands), len(set(brands)), brands)
        first_features = recs[0]["recommendation_basis"]["features"]
        self.assertIn("review_summary", recs[0])
        self.assertTrue(recs[0]["review_summary"].get("selected_comment"))
        self.assertIn("brand_popularity_bonus", first_features)
        self.assertIn("brand_signal", first_features)
        self.assertIn("entity_quality_adjustment", first_features)
        self.assertIn("distance_to_start_m", first_features)
        self.assertIn("review_count_estimate", first_features)

    def test_teahouse_query_prefers_real_teahouses_not_tea_drinks_or_chess_rooms(self):
        response = run_agent(
            {
                "goal": "春熙路附近找个茶馆",
                "city": "chengdu",
                "center_lng": 104.08099,
                "center_lat": 30.65732,
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="teahouse-entity-contract-test",
        )
        self.assertTrue(response["ok"], response)
        recs = response["result"]["variants"][0].get("recommendations", [])
        self.assertGreaterEqual(len(recs), 3)
        bad_terms = ("棋牌", "贡茶", "奶茶", "鲜泡茶", "水果茶", "冷饮")
        for rec in recs[:3]:
            self.assertEqual(rec["type"], "茶馆", rec)
            self.assertFalse(any(term in rec["name"] for term in bad_terms), rec)
            signals = rec["recommendation_basis"]["features"].get("entity_quality_signals", [])
            self.assertIn("real_teahouse_entity", signals, rec)

    def test_nearby_sight_query_stays_as_curated_recommendations(self):
        response = run_agent(
            {
                "goal": "武侯祠附近看景点",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="nearby-sight-contract-test",
        )
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual(result["center"]["center_key"], "wuhouci")
        self.assertEqual(result["constraints"].get("intent_type"), "single_poi")
        recs = result["variants"][0].get("recommendations", [])
        self.assertTrue(recs)
        self.assertFalse(result["variants"][0].get("route", []))
        self.assertTrue(all(rec["category"] == "景点" for rec in recs), recs)

    def test_shopping_and_coffee_query_preserves_both_requested_types(self):
        response = run_agent(
            {
                "goal": "太古里附近逛街喝咖啡",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="shopping-coffee-contract-test",
        )
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual(result["center"]["center_key"], "taikooli")
        self.assertEqual(result["constraints"].get("sequence"), ["商场", "饮品"])
        self.assertEqual(result["constraints"].get("time_budget_hours"), 2.5)
        items = result["variants"][0].get("route") or result["variants"][0].get("recommendations", [])
        types = {item["type"] for item in items}
        self.assertIn("饮品", types, items)
        self.assertIn("商场", types, items)
        route = result["variants"][0].get("route", [])
        self.assertTrue(route, result["variants"][0])
        feasibility = result["variants"][0].get("route_feasibility")
        self.assertIsInstance(feasibility, dict)
        self.assertTrue(feasibility.get("feasible"), feasibility)
        self.assertGreater(feasibility.get("total_move_distance_m", 0), 0)
        self.assertLessEqual(
            feasibility.get("total_move_time_min", 0),
            feasibility.get("policy", {}).get("max_total_move_time_min", 999),
            feasibility,
        )
        self.assertLessEqual(
            feasibility.get("max_detour_ratio", 0),
            feasibility.get("policy", {}).get("max_detour_ratio", 999),
            feasibility,
        )
        self.assertIn("polyline", route[0].get("move_from_start", {}))
        if len(route) > 1:
            self.assertIn("polyline", route[1].get("move_from_prev", {}))

    def test_coffee_query_prefers_coffee_named_places(self):
        response = run_agent(
            {
                "goal": "春熙路附近喝咖啡",
                "city": "chengdu",
                "center_lng": 104.08099,
                "center_lat": 30.65732,
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="coffee-entity-contract-test",
        )
        self.assertTrue(response["ok"], response)
        recs = response["result"]["variants"][0].get("recommendations", [])
        self.assertGreaterEqual(len(recs), 3)
        for rec in recs[:3]:
            name_lower = rec["name"].lower()
            self.assertTrue(any(term in name_lower for term in ("咖啡", "coffee", "cafe", "caffee", "nespresso")), rec)
            signals = rec["recommendation_basis"]["features"].get("entity_quality_signals", [])
            self.assertIn("coffee_name_match", signals, rec)

    def test_supermarket_and_snack_route_preserves_both_requested_types(self):
        response = run_agent(
            {
                "goal": "附近找个超市顺便吃点小吃",
                "city": "chengdu",
                "radius": 2500,
                "user_mode": "resident",
            },
            request_id="supermarket-snack-contract-test",
        )
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual(result["constraints"].get("sequence"), ["超市", "小吃"])
        route = result["variants"][0].get("route", [])
        types = {step["type"] for step in route}
        self.assertIn("超市", types, route)
        self.assertIn("小吃", types, route)

    def test_night_drinks_and_late_snack_route_preserves_both_types(self):
        response = run_agent(
            {
                "goal": "九眼桥附近晚上喝酒，顺便找点夜宵",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="night-drinks-contract-test",
        )
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual(result["center"]["center_key"], "jiuyanqiao")
        self.assertEqual(result["constraints"].get("sequence"), ["酒吧", "小吃"])
        route = result["variants"][0].get("route", [])
        types = {step["type"] for step in route}
        self.assertIn("酒吧", types, route)
        self.assertIn("小吃", types, route)

    def test_business_lunch_and_coffee_route_preserves_both_types(self):
        response = run_agent(
            {
                "goal": "天府广场附近出差，1小时内找午餐和咖啡",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "business",
            },
            request_id="business-lunch-coffee-contract-test",
        )
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual(result["constraints"].get("sequence"), ["中餐", "饮品"])
        self.assertEqual(result["constraints"].get("time_budget_hours"), 1)
        self.assertEqual(result["constraints"].get("time_budget_source"), "explicit")
        variant = result["variants"][0]
        items = variant.get("route") or variant.get("recommendations") or []
        types = {step["type"] for step in items}
        self.assertIn("中餐", types, items)
        self.assertIn("饮品", types, items)

    def test_route_does_not_fill_with_low_value_pois(self):
        response = run_agent(
            {
                "goal": "成都一日游",
                "city": "chengdu",
                "radius": 3000,
                "user_mode": "tourist",
            },
            request_id="route-quality-contract-test",
        )
        self.assertTrue(response["ok"], response)
        routes = [v.get("route", []) for v in response["result"]["variants"]]
        self.assertTrue(any(routes), response["result"])
        bad_terms = ("民宿", "酒店", "套一", "投影", "地暖", "专卖", "销售", "经营部")
        for route in routes:
            for step in route:
                self.assertNotIn(step["type"], {"其他", "住宿", "医疗", "培训", "汽车"}, step)
                self.assertFalse(any(term in step["name"] for term in bad_terms), step)

    def test_route_feasibility_rejects_detours_and_excessive_total_movement(self):
        policy = _route_feasibility_policy({
            "time_budget_hours": 2,
            "mode": "walk",
            "user_mode": "tourist",
            "intent_type": "simple_route",
        })

        ok, detail = _segment_route_feasible(
            dist_m=900,
            time_min=11,
            direct_m=800,
            policy=policy,
            cumulative_move_time=0,
            cumulative_move_distance=0,
        )
        self.assertTrue(ok, detail)

        ok, detail = _segment_route_feasible(
            dist_m=2800,
            time_min=35,
            direct_m=500,
            policy=policy,
            cumulative_move_time=0,
            cumulative_move_distance=0,
        )
        self.assertFalse(ok, detail)
        self.assertIn(detail["reason"], {"segment_too_long", "detour_ratio_too_high"})

        ok, detail = _segment_route_feasible(
            dist_m=900,
            time_min=11,
            direct_m=850,
            policy=policy,
            cumulative_move_time=policy["max_total_move_time_min"],
            cumulative_move_distance=policy["max_total_move_distance_m"],
        )
        self.assertFalse(ok, detail)
        self.assertIn(detail["reason"], {"total_move_time_too_high", "total_move_distance_too_high"})


if __name__ == "__main__":
    unittest.main()
