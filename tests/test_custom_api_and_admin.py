import re
# tests/test_custom_api_and_admin.py
import unittest
import json
import base64
from fastapi.testclient import TestClient
from server import app
import core.db as db

class TestCustomApiAndAdmin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.client = TestClient(app)

        # Authenticate admin by creating session token directly
        admin_u = db.get_user_by_username("admin")
        cls.admin_user = admin_u
        cls.admin_token = db.create_auth_token_session(admin_u["id"])
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}
        cls.admin_cookies = {"cogni_session": cls.admin_token}

        # Create or fetch test student
        cls.test_student_uname = "test_stu_api_01"
        existing = db.get_user_by_username(cls.test_student_uname)
        if not existing:
            stu = db.create_user(cls.test_student_uname, "Student123456!", "测试学生01", "student", class_name="高一(1)班")
        else:
            stu = existing
        cls.student_user = stu
        cls.student_token = db.create_auth_token_session(stu["id"])
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}
        cls.student_cookies = {"cogni_session": cls.student_token}

    def test_01_api_key_encryption_roundtrip(self):
        raw_key = "sk-0123456789abcdef0123456789abcdef"
        enc = db.encrypt_api_key(raw_key)
        self.assertNotEqual(raw_key, enc)
        dec = db.decrypt_api_key(enc)
        self.assertEqual(raw_key, dec)

    def test_02_custom_api_key_endpoints(self):
        # 1. Check initially empty
        res = self.client.get("/api/user/custom_api_key", headers=self.student_headers, cookies=self.student_cookies)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data.get("has_custom_key"))
        self.assertEqual(data.get("mode"), "school")

        # 2. Try binding invalid key format
        res_bad = self.client.post("/api/user/custom_api_key", headers=self.student_headers, cookies=self.student_cookies, json={"api_key": "not-sk-key"})
        self.assertEqual(res_bad.status_code, 400)
        self.assertIn("sk-", res_bad.json().get("detail", ""))

        # 3. Simulate directly setting in DB (to bypass external DeepSeek probe in unit test)
        valid_key = "sk-deepseek-mock-test-key-9988776655"
        db.set_user_custom_api_key(self.student_user["id"], valid_key)

        res_bound = self.client.get("/api/user/custom_api_key", headers=self.student_headers, cookies=self.student_cookies)
        self.assertEqual(res_bound.status_code, 200)
        data_bound = res_bound.json()
        self.assertTrue(data_bound.get("has_custom_key"))
        self.assertEqual(data_bound.get("mode"), "custom")
        self.assertTrue(data_bound.get("masked_key").startswith("sk-"))

        # 4. Delete / unbind
        res_del = self.client.delete("/api/user/custom_api_key", headers=self.student_headers, cookies=self.student_cookies)
        self.assertEqual(res_del.status_code, 200)
        res_after = self.client.get("/api/user/custom_api_key", headers=self.student_headers, cookies=self.student_cookies)
        self.assertFalse(res_after.json().get("has_custom_key"))

    def test_03_admin_cannot_delete_self(self):
        admin_u = self.admin_user
        res = self.client.delete(f"/api/admin/users/{admin_u['id']}", headers=self.admin_headers, cookies=self.admin_cookies)
        self.assertEqual(res.status_code, 400)
        self.assertIn("安全保护", res.json().get("detail", ""))

    def test_04_soft_delete_and_trash_bin(self):
        # Create a temp student to delete
        temp_uname = "temp_del_stu_99"
        existing = db.get_user_by_username(temp_uname)
        if existing:
            db.purge_user(existing["id"], "other_admin")

        db.create_user(temp_uname, "TempPassword123!", "临时删除学生", "student", class_name="高一(2)班")
        temp_u = db.get_user_by_username(temp_uname)
        self.assertIsNotNone(temp_u)

        # Soft delete via admin endpoint
        res_del = self.client.delete(f"/api/admin/users/{temp_u['id']}", headers=self.admin_headers, cookies=self.admin_cookies)
        self.assertEqual(res_del.status_code, 200)

        # Verify not in active users list
        users = db.list_all_users()
        active_unames = [u["username"] for u in users]
        self.assertNotIn(temp_uname, active_unames)

        # Verify in trash bin
        res_trash = self.client.get("/api/admin/trash/items", headers=self.admin_headers, cookies=self.admin_cookies)
        self.assertEqual(res_trash.status_code, 200)
        trash_users = res_trash.json().get("trash", {}).get("users", [])
        trash_unames = [u["username"] for u in trash_users]
        self.assertIn(temp_uname, trash_unames)

        # Restore from trash
        res_restore = self.client.post("/api/admin/users/batch_actions", headers=self.admin_headers, cookies=self.admin_cookies, json={
            "action": "restore",
            "user_ids": [temp_u["id"]]
        })
        self.assertEqual(res_restore.status_code, 200)
        self.assertEqual(res_restore.json().get("result", {}).get("success"), 1)

        # Verify restored to active
        users_after = db.list_all_users()
        self.assertIn(temp_uname, [u["username"] for u in users_after])

        # Purge
        res_purge = self.client.post("/api/admin/users/batch_actions", headers=self.admin_headers, cookies=self.admin_cookies, json={
            "action": "purge",
            "user_ids": [temp_u["id"]]
        })
        self.assertEqual(res_purge.status_code, 200)
        self.assertIsNone(db.get_user_by_id(temp_u["id"], include_deleted=True))

    def test_05_batch_table_paste_student_only(self):
        # Format: 账号, 密码, 姓名, 班级
        for uname in ["stu_batch_01", "stu_batch_02"]:
            old = db.get_user_by_username(uname, include_deleted=True)
            if old:
                db.purge_user(old["id"], "other_admin")

        table_content = """
stu_batch_01, Student123456!, 张三, 高一(3)班
stu_batch_02, Student123456!, 李四, 高一(3)班
"""
        res = self.client.post("/api/admin/users/batch", headers=self.admin_headers, cookies=self.admin_cookies, json={
            "mode": "table",
            "table_text": table_content
        })
        self.assertEqual(res.status_code, 200)
        results = res.json().get("results", {})
        self.assertEqual(results.get("success_count"), 2)

        # Verify both are students with class_name
        u1 = db.get_user_by_username("stu_batch_01")
        self.assertIsNotNone(u1)
        self.assertEqual(u1.get("role"), "student")
        self.assertEqual(u1.get("class_name"), "高一(3)班")
        self.assertEqual(u1.get("display_name"), "张三")

        # Cleanup
        db.purge_user(u1["id"], "other_admin")
        u2 = db.get_user_by_username("stu_batch_02")
        if u2:
            db.purge_user(u2["id"], "other_admin")

    def test_06_class_report_and_csv(self):
        # 1. JSON report
        res = self.client.get("/api/admin/analytics/class_report", headers=self.admin_headers, cookies=self.admin_cookies)
        self.assertEqual(res.status_code, 200)
        rep = res.json().get("report", {})
        self.assertIn("student_count", rep)
        self.assertIn("student_reports", rep)

        # 2. CSV report
        res_csv = self.client.get("/api/admin/analytics/class_report?format=csv", headers=self.admin_headers, cookies=self.admin_cookies)
        self.assertEqual(res_csv.status_code, 200)
        self.assertIn("text/csv", res_csv.headers.get("content-type", ""))
        self.assertTrue(res_csv.content.startswith(b"\xef\xbb\xbf"))  # UTF-8 BOM
        csv_text = res_csv.content.decode("utf-8")
        self.assertIn("学号/账号", csv_text)
        self.assertIn("达成突破数", csv_text)

    def test_07_trash_items_and_compatibility(self):
        # 1. Trash items endpoint
        res = self.client.get("/api/admin/trash/items", headers=self.admin_headers, cookies=self.admin_cookies)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("trash", data)
        self.assertIn("users", data["trash"])
        self.assertIn("sessions", data["trash"])

        # 2. Check HTML integrity for Trash panel and top navbar username display
        with open("static/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        # adminPanelSecurity must close before adminPanelTrash
        sec_idx = html.index('id="adminPanelSecurity"')
        trash_idx = html.index('id="adminPanelTrash"')
        self.assertTrue(sec_idx < trash_idx)
        sec_slice = html[sec_idx:trash_idx]
        self.assertEqual(len(re.findall(r'<div\b', sec_slice)), len(re.findall(r'</div>', sec_slice)))

        # Top navbar displays display_name by default
        self.assertIn("userNameText.textContent = displayLabel", html)

        # Badges have nowrap
        self.assertIn(".user-status-badge {", html)
        self.assertIn("white-space: nowrap !important;", html)

        # Version is v2.9.0
        self.assertIn("<span>v2.9.0</span>", html)
        self.assertIn("const APP_CURRENT_VERSION = 'v2.9.0';", html)

if __name__ == "__main__":
    unittest.main()
