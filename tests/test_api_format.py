"""
API 响应格式测试
验证 v1/v2 响应格式符合规范
"""
import json
import unittest
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_app import _to_v2_envelope


class TestV2Envelope(unittest.TestCase):
    def test_success_response(self):
        v1 = {"ok": True, "result": {"variants": []}, "request_id": "abc123"}
        v2 = _to_v2_envelope(v1, "abc123")
        self.assertEqual(v2["code"], 200)
        self.assertEqual(v2["msg"], "success")
        self.assertEqual(v2["request_id"], "abc123")
        self.assertIn("data", v2)
        self.assertNotIn("ok", v2["data"])

    def test_error_response(self):
        v1 = {"ok": False, "error": "参数错误", "error_code": "INVALID_PAYLOAD", "request_id": "abc123"}
        v2 = _to_v2_envelope(v1, "abc123")
        self.assertEqual(v2["code"], 400)
        self.assertEqual(v2["msg"], "参数错误")
        self.assertEqual(v2["error_code"], "INVALID_PAYLOAD")
        self.assertIsNone(v2["data"])

    def test_error_code_mapping(self):
        from web_app import _error_code_to_http
        self.assertEqual(_error_code_to_http("EMPTY_GOAL"), 400)
        self.assertEqual(_error_code_to_http("UNSUPPORTED_SERVICE_AREA"), 422)
        self.assertEqual(_error_code_to_http("NO_POI"), 404)
        self.assertEqual(_error_code_to_http("DATA_NOT_READY"), 503)
        self.assertEqual(_error_code_to_http("INTERNAL_ERROR"), 500)
        self.assertEqual(_error_code_to_http("UNKNOWN"), 500)


class TestMockApiFormat(unittest.TestCase):
    def test_search_pois_format(self):
        """验证 mock_api search_pois 返回格式与高德 API 一致"""
        from mock_api import MockApiClient
        client = MockApiClient(city="chengdu", simulate_latency_ms=0, simulate_quota=False)
        resp = client.search_pois(104.082, 30.657, radius=1000, page_size=10)

        # 高德 API 标准字段
        self.assertIn("status", resp)
        self.assertIn("info", resp)
        self.assertIn("count", resp)
        self.assertIn("pois", resp)

        if resp["pois"]:
            poi = resp["pois"][0]
            self.assertIn("id", poi)
            self.assertIn("name", poi)
            self.assertIn("type", poi)
            self.assertIn("location", poi)
            self.assertIn("address", poi)

    def test_poi_detail_format(self):
        """验证 mock_api get_poi_detail 返回格式"""
        from mock_api import MockApiClient
        client = MockApiClient(city="chengdu", simulate_latency_ms=0, simulate_quota=False)

        # 先搜索一个 POI
        search = client.search_pois(104.082, 30.657, radius=1000, page_size=1)
        if not search["pois"]:
            self.skipTest("No POI found")

        poi_id = search["pois"][0]["id"]
        detail = client.get_poi_detail(poi_id)

        self.assertEqual(detail["status"], "1")
        self.assertIn("poi", detail)
        self.assertIn("name", detail["poi"])

    def test_walking_route_format(self):
        """验证 mock_api get_walking_route 返回格式与高德一致"""
        from mock_api import MockApiClient
        client = MockApiClient(city="chengdu", simulate_latency_ms=0, simulate_quota=False)

        resp = client.get_walking_route(104.082, 30.657, 104.085, 30.660)
        self.assertEqual(resp["status"], "1")
        self.assertIn("route", resp)
        self.assertIn("paths", resp["route"])


if __name__ == "__main__":
    unittest.main()
