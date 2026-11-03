# tests/test_sse_headers.py
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import app
from core.db import init_db

class TestSSEHeaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        login_res = cls.client.post("/api/auth/login", json={"username": "student01", "password": "Student@2026!"})
        if login_res.status_code == 200:
            token = login_res.json()["token"]
            cls.headers = {"Authorization": f"Bearer {token}"}
        else:
            cls.headers = {}

    @patch("server.stream_tutor_response")
    def test_sse_streaming_headers(self, mock_stream):
        def dummy_gen():
            yield "测试回复"
        mock_stream.return_value = dummy_gen()

        # 创建并开题
        create_res = self.client.post("/api/sessions/create", headers=self.headers)
        self.assertEqual(create_res.status_code, 200)
        s_id = create_res.json()["store"]["current_session_id"]

        init_res = self.client.post(
            "/api/sessions/init_question",
            json={"session_id": s_id, "question": "测试题目：小车运动"},
            headers=self.headers
        )
        self.assertEqual(init_res.status_code, 200)

        # 发起聊天流式请求 (POST)
        resp = self.client.post(
            f"/api/sessions/{s_id}/chat/stream",
            json={"student_text": "小车受力测试"},
            headers=self.headers
        )
        headers = {k.lower(): v for k, v in resp.headers.items()}
        print("\n[Current SSE Headers]:", {k: v for k, v in headers.items() if "buffering" in k or "cache" in k or "content-type" in k})
        
        # 严格断言反向代理防缓冲与防缓存响应头
        self.assertIn("x-accel-buffering", headers, "Missing X-Accel-Buffering header! Nginx will buffer SSE stream!")
        self.assertEqual(headers.get("x-accel-buffering"), "no")
        self.assertIn("cache-control", headers)
        self.assertIn("no-cache", headers.get("cache-control", ""))

if __name__ == "__main__":
    unittest.main()
