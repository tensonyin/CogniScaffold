import unittest
import os
import sys
import re
import uuid
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath("."))
import core.db as db
import server

class TestSixImprovements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.client = TestClient(server.app)

    def test_01_sessions_close_restore_no_name_error(self):
        """Fix for Item 6: Ensure close, reorder, restore, delete_archived do not throw NameError on is_admin"""
        res = self.client.post("/api/auth/login", json={"username": "student01", "password": "Student@2026!"})
        self.assertEqual(res.status_code, 200)
        token = res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create a test session
        c_res = self.client.post("/api/sessions/create", headers=headers)
        self.assertEqual(c_res.status_code, 200)
        s_id = c_res.json()["store"]["current_session_id"]

        # 2. Close session (must not throw 500 NameError)
        close_res = self.client.post("/api/sessions/close", json={"session_id": s_id}, headers=headers)
        self.assertEqual(close_res.status_code, 200, f"close_session failed: {close_res.text}")
        self.assertIn("store", close_res.json())

        # 3. Restore session (must not throw 500 NameError)
        rest_res = self.client.post("/api/sessions/restore", json={"session_id": s_id}, headers=headers)
        self.assertEqual(rest_res.status_code, 200, f"restore_session failed: {rest_res.text}")

        # 4. Close again and delete archived (must not throw 500 NameError)
        self.client.post("/api/sessions/close", json={"session_id": s_id}, headers=headers)
        del_res = self.client.post("/api/sessions/delete_archived", json={"session_id": s_id}, headers=headers)
        self.assertEqual(del_res.status_code, 200, f"delete_archived failed: {del_res.text}")

    def test_02_security_question_and_first_login_flag(self):
        """Item 3: New user must set security question & new password, and verify question endpoint"""
        # Create a fresh unique test user
        uname = f"test_sec_{uuid.uuid4().hex[:8]}"
        pwd = "Default@2026!"
        db.create_user(uname, pwd, display_name="测试密保用户", must_change_password=1)

        # Login
        res = self.client.post("/api/auth/login", json={"username": uname, "password": pwd})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("must_setup_security"), "New user should have must_setup_security=True")
        token = data["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Setup security and new password
        setup_res = self.client.post("/api/auth/setup_security_and_password", json={
            "new_password": "NewStrongPass@2026!",
            "security_question": "您就读的第一所小学或初中全称是？",
            "security_answer": "实验小学"
        }, headers=headers)
        self.assertEqual(setup_res.status_code, 200)

        # Retrieve security question
        q_res = self.client.get(f"/api/auth/security_question?username={uname}")
        self.assertEqual(q_res.status_code, 200)
        self.assertEqual(q_res.json()["question"], "您就读的第一所小学或初中全称是？")

        # Verify security answer (Step 1 of Forgot Password)
        v_res = self.client.post("/api/auth/verify_security_answer", json={
            "username": uname,
            "security_answer": "实验小学"
        })
        self.assertEqual(v_res.status_code, 200)
        reset_token = v_res.json().get("reset_token")
        self.assertIsNotNone(reset_token)

        # Reset password (Step 2 of Forgot Password)
        r_res = self.client.post("/api/auth/reset_password", json={
            "reset_token": reset_token,
            "new_password": "ResetPass@2026!"
        })
        self.assertEqual(r_res.status_code, 200)

        # Login with newly reset password
        login2 = self.client.post("/api/auth/login", json={"username": uname, "password": "ResetPass@2026!"})
        self.assertEqual(login2.status_code, 200)
        self.assertFalse(login2.json().get("must_setup_security", False))

    def test_03_dashboard_collapsed_pill_position(self):
        """Item 1: .dashboard-collapsed-pill should not be positioned at top 50% to prevent collision with camera button"""
        with open("static/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        match = re.search(r'\.dashboard-collapsed-pill\s*\{([^}]+)\}', html)
        self.assertIsNotNone(match)
        css = match.group(1)
        self.assertNotIn("top: 50%", css, ".dashboard-collapsed-pill should not be at top: 50%")
        self.assertTrue("top: 1" in css or "top: 2" in css or "top: 12" in css or "top: 13" in css or "top: 14" in css, "Pill should have safe top offset")

    def test_04_touch_zoom_prevention_script(self):
        """Item 5: Script should prevent multi-touch zoom and wheel zoom while allowing keyboard zoom and pinch-out recovery"""
        with open("static/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("user-scalable=no", html)
        self.assertIn("minimum-scale=1.0", html)
        self.assertIn("touch-action: pan-x pan-y", html)
        self.assertIn("gesturechange", html)
        self.assertIn("forceResetViewportScale", html)
        self.assertIn("calcTouchDistance", html)
        self.assertIn("currentDistance > pinchStartDistance", html)

    def test_05_logout_forces_clean_reload(self):
        """Item 2: handleLogout should remove tokens and reload window"""
        with open("static/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        start = html.find("async function handleLogout()")
        self.assertNotEqual(start, -1, "handleLogout should exist in index.html")
        body = html[start:start+400]
        self.assertIn("localStorage.removeItem('cogni_token')", body)
        self.assertIn("window.location.reload()", body)

    def test_06_history_dual_pagination_and_spinner_feedback(self):
        """Item 4: History list pagination rendered at top and bottom, restore and delete have loading feedback"""
        with open("static/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("buildPaginationEl(true)", html, "Top pagination should be rendered")
        self.assertIn("buildPaginationEl(false)", html, "Bottom pagination should be rendered")
        self.assertIn("restoreSession('${item.id}', this)", html, "restoreSession should pass button reference")
        self.assertIn("deleteArchived('${item.id}', this)", html, "deleteArchived should pass button reference")
        self.assertIn("恢复中...", html, "restoreSession should show loading spinner and text")
        self.assertIn("删除中...", html, "deleteArchived should show loading spinner and text")

    def test_07_tab_close_optimistic_removal(self):
        """Item 6: closeTab should immediately remove active session and re-render tabs"""
        with open("static/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("delete appState.active_sessions[id]", html)
        self.assertIn("renderTabs()", html)

if __name__ == '__main__':
    unittest.main()
