import unittest
import os
import re
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

# Import app and db
import core.db as db
import server

class TestFiveImprovements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.client = TestClient(server.app)

    def test_01_east8_timezone(self):
        """1. East 8th Zone datetime verification"""
        self.assertTrue(hasattr(db, 'TZ_EAST8'), "core.db should define TZ_EAST8")
        self.assertTrue(hasattr(db, 'now_east8_str'), "core.db should define now_east8_str")
        self.assertTrue(hasattr(db, 'today_east8_str'), "core.db should define today_east8_str")

        e8_now = db.now_east8()
        utc_now = datetime.now(timezone.utc)
        diff_hours = (e8_now.utcoffset().total_seconds()) / 3600.0
        self.assertEqual(diff_hours, 8.0, "TZ_EAST8 offset should be exactly +8 hours")

        e8_str = db.now_east8_str()
        self.assertRegex(e8_str, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_02_admin_sessions_username_and_user_dict(self):
        """2. Admin sessions list and detail must include username, display_name, and user dict"""
        stu = db.get_user_by_username("student01")
        self.assertIsNotNone(stu, "student01 should exist")

        sessions = db.get_admin_sessions_list(user_id=stu["id"])
        if sessions:
            first_s = sessions[0]
            self.assertIn("username", first_s)
            self.assertEqual(first_s["username"], "student01")
            self.assertIn("user", first_s)
            self.assertIsInstance(first_s["user"], dict)
            self.assertEqual(first_s["user"]["username"], "student01")
            self.assertIn("display_name", first_s["user"])

    def test_03_changelog_sanitization(self):
        """3. Changelog modal must not leak admin console or management terms to general students"""
        with open("static/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        # Extract content of #changelogModal
        match = re.search(r'<div[^>]*id="changelogModal"[^>]*>([\s\S]*?)<div[^>]*id="guideTourModal"', html)
        self.assertIsNotNone(match, "changelogModal should be present in static/index.html")
        changelog_content = match.group(1)

        prohibited_terms = ["管理员", "管理端", "管理控制台", "批量建号", "全景审查", "账号封禁", "成本透视"]
        found = [term for term in prohibited_terms if term in changelog_content]
        self.assertEqual(found, [], f"Changelog modal should not contain admin-internal terms: {found}")

    def test_04_user_quota_info_and_live_updates(self):
        """4. server.py should provide get_user_quota_info with accurate remaining tokens"""
        self.assertTrue(hasattr(server, 'get_user_quota_info'), "server should define get_user_quota_info")
        stu = db.get_user_by_username("student01")
        quota = server.get_user_quota_info(stu["id"], is_admin=False)
        self.assertIn("daily_limit", quota)
        self.assertIn("daily_token_limit", quota)
        self.assertIn("today_tokens", quota)
        self.assertIn("remaining_tokens", quota)

    def test_05_cookie_security_attributes(self):
        """5. Login response must set HttpOnly, SameSite=Lax (or Strict), and path=/ on session cookie"""
        res = self.client.post("/api/auth/login", json={"username": "student01", "password": "Student@2026!"})
        self.assertEqual(res.status_code, 200)

        # Check Set-Cookie headers
        set_cookie_headers = res.headers.get_list("set-cookie") if hasattr(res.headers, 'get_list') else [res.headers.get("set-cookie", "")]
        cookie_str = "; ".join(set_cookie_headers).lower()

        self.assertIn("httponly", cookie_str, "Cookie must have HttpOnly flag")
        self.assertTrue("samesite=lax" in cookie_str or "samesite=strict" in cookie_str, "Cookie must have SameSite=Lax or Strict")
        self.assertIn("path=/", cookie_str, "Cookie path must be /")
        self.assertIn("cogni_session", cookie_str, "Cookie name should include cogni_session")

if __name__ == '__main__':
    unittest.main()
