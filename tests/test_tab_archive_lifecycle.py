import os
import sys
import json
import unittest

sys.path.insert(0, os.path.abspath("."))
from core.db import (
    get_db_connection,
    init_db,
    get_user_store,
    archive_user_session,
    restore_user_session,
    set_user_current_session,
    _seed_student01_golden_presets,
)


class TestTabArchiveLifecycle(unittest.TestCase):
    def test_archived_sessions_survive_init_db(self):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = 'student01';")
        stu_row = cur.fetchone()
        self.assertIsNotNone(stu_row, "student01 must exist")
        stu_id = stu_row["id"]
        conn.close()

        # 1. Get initial store
        store = get_user_store(stu_id)
        active = store["active_sessions"]
        self.assertGreater(len(active), 0, "student01 should have active sessions")

        # Pick a session to archive
        target_id = list(active.keys())[0]

        # 2. Archive it
        archive_user_session(stu_id, target_id)

        # Verify it is archived
        store_after = get_user_store(stu_id)
        self.assertNotIn(target_id, store_after["active_sessions"])
        self.assertIn(target_id, store_after["archived_sessions"])

        # Verify user_preferences current_session_id is not pointing to the archived session
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT current_session_id, session_order FROM user_preferences WHERE user_id = ?;",
            (stu_id,),
        )
        pref = cur.fetchone()
        conn.close()
        if pref:
            self.assertNotEqual(pref["current_session_id"], target_id)
            if pref["session_order"]:
                order = json.loads(pref["session_order"])
                self.assertNotIn(target_id, order)

        # 3. Simulate server restart / init_db()
        init_db()

        # 4. Check if the session is STILL archived
        store_after_init = get_user_store(stu_id)
        self.assertIn(
            target_id,
            store_after_init["archived_sessions"],
            f"REGRESSION: Session {target_id} was removed from archived_sessions after init_db()!",
        )
        self.assertNotIn(
            target_id,
            store_after_init["active_sessions"],
            f"REGRESSION: Session {target_id} was resurrected into active_sessions after init_db()!",
        )

        # 5. Pick a GOLDEN PRESET session to archive if present
        store_now = get_user_store(stu_id)
        preset_ids = [sid for sid in store_now["active_sessions"] if sid.startswith("preset_")]
        if preset_ids:
            preset_target = preset_ids[0]
            archive_user_session(stu_id, preset_target)

            # Verify it is archived
            store_preset_arch = get_user_store(stu_id)
            self.assertNotIn(preset_target, store_preset_arch["active_sessions"])
            self.assertIn(preset_target, store_preset_arch["archived_sessions"])

            # Simulate init_db() again
            init_db()

            # Verify it STAYED archived!
            store_after_init2 = get_user_store(stu_id)
            self.assertIn(
                preset_target,
                store_after_init2["archived_sessions"],
                f"REGRESSION: Golden preset {preset_target} was resurrected from archived after init_db()!",
            )
            self.assertNotIn(
                preset_target,
                store_after_init2["active_sessions"],
                f"REGRESSION: Golden preset {preset_target} reappeared in active tabs after init_db()!",
            )

        # Restore test session to active
        restore_user_session(stu_id, target_id)


if __name__ == "__main__":
    unittest.main()
