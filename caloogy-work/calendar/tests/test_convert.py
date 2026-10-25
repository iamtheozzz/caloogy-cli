"""python3 -m unittest discover -s tests   (from caloogy-work/calendar, with src/ on PYTHONPATH)"""
import json
import unittest
from datetime import timedelta, timezone

from caloogy_calendar.convert import events_in, export_event, key_of, load_foreign, to_caloogy, to_ics

SH = timezone(timedelta(hours=8))
NY = timezone(timedelta(hours=-4))


class ToCaloogy(unittest.TestCase):
    def test_feishu_timestamps(self):
        e = {"summary": "Review", "start_time": {"timestamp": "1761631200", "timezone": "Asia/Shanghai"},
             "end_time": {"timestamp": "1761634800"}, "location": {"name": "Room 5"},
             "vchat": {"meeting_url": "https://vc.feishu.cn/j/123"}, "attendees": [{"display_name": "Ann"}, {"display_name": "Bo"}]}
        [p] = to_caloogy(e, SH)
        self.assertEqual((p["date"], p["start"], p["end"], p["title"]), ("2025-10-28", "14:00", "15:00", "Review"))
        self.assertEqual(p["location"], "Room 5")
        self.assertEqual(p["meeting_url"], "https://vc.feishu.cn/j/123")
        self.assertEqual(p["attendees"], ["Ann", "Bo"])

    def test_converted_to_local_zone(self):
        [p] = to_caloogy({"title": "Call", "start": "2026-10-25T09:00:00+08:00", "end": "2026-10-25T10:00:00+08:00"}, NY)
        self.assertEqual((p["date"], p["start"], p["end"]), ("2026-10-24", "21:00", "22:00"))

    def test_crossing_midnight_is_split(self):
        ps = to_caloogy({"title": "Flight", "start": "2026-10-25T22:00+08:00", "end": "2026-10-26T02:30+08:00"}, SH)
        self.assertEqual([(p["date"], p["start"], p["end"]) for p in ps],
                         [("2026-10-25", "22:00", "24:00"), ("2026-10-26", "00:00", "02:30")])

    def test_ending_at_midnight_is_one_piece(self):
        ps = to_caloogy({"title": "Late", "start": "2026-10-25T23:00+08:00", "end": "2026-10-26T00:00+08:00"}, SH)
        self.assertEqual([(p["date"], p["start"], p["end"]) for p in ps], [("2026-10-25", "23:00", "24:00")])

    def test_all_day_inclusive_and_exclusive(self):
        e = {"summary": "Trip", "start_time": {"date": "2026-10-25"}, "end_time": {"date": "2026-10-27"}}
        self.assertEqual([p["date"] for p in to_caloogy(e, SH, "inclusive")], ["2026-10-25", "2026-10-26", "2026-10-27"])
        self.assertEqual([p["date"] for p in to_caloogy(e, SH, "exclusive")], ["2026-10-25", "2026-10-26"])
        one = {"summary": "Holiday", "start": {"date": "2026-10-25"}, "end": {"date": "2026-10-25"}}
        self.assertEqual([p["date"] for p in to_caloogy(one, SH, "exclusive")], ["2026-10-25"])
        self.assertTrue(all(p["start"] is None for p in to_caloogy(e, SH)))

    def test_cancelled_skipped(self):
        self.assertEqual(to_caloogy({"summary": "x", "status": "cancelled", "start": "2026-10-25T10:00+08:00"}, SH), [])

    def test_no_end(self):
        [p] = to_caloogy({"title": "Coffee", "start": "2026-10-25 11:00"}, SH)
        self.assertEqual((p["start"], p["end"]), ("11:00", None))

    def test_title_starting_with_a_time(self):
        [p] = to_caloogy({"title": "10:00 sync", "start": {"date": "2026-10-25"}}, SH)
        self.assertFalse(p["title"].startswith("10:00"))

    def test_our_own_export_round_trips(self):
        [p] = to_caloogy({"title": "Gym", "date": "2026-10-25", "start": "7:00", "end": "08:00"}, SH)
        self.assertEqual((p["date"], p["start"], p["end"]), ("2026-10-25", "07:00", "08:00"))
        ex = export_event({"id": "x", "title": "Gym", "date": "2026-10-25", "start": "07:00", "end": None}, SH)
        self.assertEqual((ex["start_iso"], ex["end_iso"]), ("2026-10-25T07:00+08:00", "2026-10-25T07:30+08:00"))
        [back] = to_caloogy({"summary": ex["title"], "start_time": ex["start_iso"], "end_time": ex["end_iso"]}, SH)
        self.assertEqual(key_of(back), key_of({"date": "2026-10-25", "start": "07:00", "title": "gym"}))


class Inputs(unittest.TestCase):
    def test_wrapped_lists(self):
        self.assertEqual(len(events_in({"data": {"items": [{"summary": "a"}, {"summary": "b"}]}})), 2)
        self.assertEqual(len(events_in([{"date": "2026-10-25", "events": [{"summary": "a"}]}])), 1)
        self.assertEqual(events_in({"ok": True, "data": []}), [])

    def test_ics(self):
        ics = "\r\n".join([
            "BEGIN:VCALENDAR", "BEGIN:VEVENT", "SUMMARY:Dentist\\, Dr. Li", "DTSTART;TZID=Asia/Shanghai:20261025T150000",
            "DTEND;TZID=Asia/Shanghai:20261025T160000", "LOCATION:Main St", "END:VEVENT",
            "BEGIN:VEVENT", "SUMMARY:Holiday", "DTSTART;VALUE=DATE:20261026", "DTEND;VALUE=DATE:20261027", "END:VEVENT",
            "BEGIN:VEVENT", "SUMMARY:Weekly", "DTSTART:20261025T010000Z", "RRULE:FREQ=WEEKLY", "END:VEVENT", "END:VCALENDAR"])
        pieces, info = load_foreign(ics, SH)
        self.assertEqual(info["skipped_recurring"], 1)
        self.assertEqual([(p["date"], p["start"], p["end"], p["title"]) for p in pieces],
                         [("2026-10-25", "15:00", "16:00", "Dentist, Dr. Li"), ("2026-10-26", None, None, "Holiday")])

    def test_ics_out_and_back(self):
        evs = [{"id": "2026-10-25-aaaaaaaa", "title": "A, b", "date": "2026-10-25", "start": "09:00", "end": "24:00"},
               {"id": "2026-10-26-bbbbbbbb", "title": "All day", "date": "2026-10-26", "start": None, "end": None}]
        pieces, _ = load_foreign(to_ics(evs, SH), SH)
        self.assertEqual([(p["date"], p["start"], p["end"], p["title"]) for p in pieces],
                         [("2026-10-25", "09:00", "24:00", "A, b"), ("2026-10-26", None, None, "All day")])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            load_foreign("not json", SH)
        self.assertEqual(load_foreign(json.dumps({"nothing": 1}), SH)[0], [])
        with self.assertRaises(ValueError):       # lark-cli printed an error instead of events
            load_foreign(json.dumps({"ok": False, "error": {"message": "need_user_authorization"}}), SH)
        self.assertEqual(len(load_foreign(json.dumps({"ok": True, "data": [{"summary": "a", "start": "2026-10-25"}]}), SH)[0]), 1)


if __name__ == "__main__":
    unittest.main()
