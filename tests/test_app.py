import os
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["TODAYTIMETABLE_DB"] = _tmp.name

import app as app_module  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")


def make_class(cid, weekday, period, subject="科目", room="", memo=""):
    return {
        "id": cid,
        "weekday": weekday,
        "period": period,
        "subject": subject,
        "room": room,
        "memo": memo,
    }


class TodayTimetableTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM classes")
            conn.commit()

    def add_via_form(self, weekday, period, subject, room="", memo=""):
        return self.client.post(
            "/classes",
            data={"weekday": weekday, "period": period, "subject": subject,
                  "room": room, "memo": memo},
        )

    def count_classes(self):
        with app_module.app.app_context():
            conn = app_module.get_db()
            return conn.execute("SELECT COUNT(*) AS c FROM classes").fetchone()["c"]

    # ---- /healthz ----
    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    # ---- 曜日別選択ロジック（純粋関数） ----
    def test_select_each_weekday(self):
        classes = [make_class(d + 1, d, 1, subject=f"科目{d}") for d in range(7)]
        for d in range(7):
            selected = app_module.classes_for_weekday(classes, d)
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["weekday"], d)
            self.assertEqual(selected[0]["subject"], f"科目{d}")

    def test_select_sorts_by_period(self):
        classes = [
            make_class(1, 2, 4, subject="4限"),
            make_class(2, 2, 1, subject="1限"),
            make_class(3, 2, 3, subject="3限"),
        ]
        selected = app_module.classes_for_weekday(classes, 2)
        self.assertEqual([c["period"] for c in selected], [1, 3, 4])
        self.assertEqual([c["subject"] for c in selected], ["1限", "3限", "4限"])

    def test_select_empty_day(self):
        classes = [make_class(1, 0, 1), make_class(2, 0, 2)]
        self.assertEqual(app_module.classes_for_weekday(classes, 5), [])
        self.assertEqual(app_module.classes_for_weekday([], 0), [])

    def test_today_weekday_matches_jst(self):
        self.assertEqual(app_module.today_weekday(), datetime.now(JST).weekday())

    # ---- 登録・表示 ----
    def test_add_class_appears_on_week_page(self):
        res = self.add_via_form(0, 2, "数学", room="201", memo="教科書持参")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.count_classes(), 1)
        page = self.client.get("/week/0").get_data(as_text=True)
        self.assertIn("数学", page)
        self.assertIn("201", page)
        self.assertIn("教科書持参", page)

    def test_add_class_sorted_on_week_page(self):
        self.add_via_form(3, 5, "五限の科目")
        self.add_via_form(3, 1, "一限の科目")
        page = self.client.get("/week/3").get_data(as_text=True)
        self.assertLess(page.index("一限の科目"), page.index("五限の科目"))

    def test_today_page_shows_only_todays_classes(self):
        today = datetime.now(JST).weekday()
        other = (today + 1) % 7
        self.add_via_form(today, 1, "今日の科目")
        self.add_via_form(other, 1, "別の曜日の科目")
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("今日の科目", page)
        self.assertNotIn("別の曜日の科目", page)

    def test_today_page_empty_message(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("今日の授業はありません", page)

    def test_week_page_empty_message(self):
        page = self.client.get("/week/6").get_data(as_text=True)
        self.assertIn("まだ登録されていません", page)

    # ---- バリデーション ----
    def test_add_requires_subject(self):
        self.add_via_form(1, 1, "")
        self.assertEqual(self.count_classes(), 0)

    def test_add_rejects_invalid_period(self):
        self.add_via_form(1, 0, "範囲外")
        self.add_via_form(1, 9, "範囲外")
        self.assertEqual(self.count_classes(), 0)

    def test_add_rejects_invalid_weekday(self):
        self.add_via_form(7, 1, "範囲外")
        self.add_via_form(-1, 1, "範囲外")
        self.assertEqual(self.count_classes(), 0)

    def test_week_page_out_of_range_404(self):
        self.assertEqual(self.client.get("/week/7").status_code, 404)

    # ---- 削除 ----
    def test_delete_class(self):
        self.add_via_form(4, 3, "削除対象")
        self.assertEqual(self.count_classes(), 1)
        with app_module.app.app_context():
            conn = app_module.get_db()
            cid = conn.execute("SELECT id FROM classes").fetchone()["id"]
        res = self.client.post(f"/classes/{cid}/delete", data={"weekday": 4})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.count_classes(), 0)
        page = self.client.get("/week/4").get_data(as_text=True)
        self.assertNotIn("削除対象", page)

    def test_room_and_memo_optional(self):
        self.add_via_form(2, 1, "教室メモなし科目")
        page = self.client.get("/week/2").get_data(as_text=True)
        self.assertIn("教室メモなし科目", page)


if __name__ == "__main__":
    unittest.main()
