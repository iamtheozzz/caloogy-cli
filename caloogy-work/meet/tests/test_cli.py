import argparse
import os
import re
import unittest

from caloogy_meet.cli import TOOLS, Fail, build_parser, link, room_id, skill_text


class Room(unittest.TestCase):
    def test_forms(self):
        for ref in ("abc-defg-hjk", "ABC-DEFG-HJK", "https://meet.caloogy.com/abc-defg-hjk", "https://call.caloogy.com/abc-defg-hjk/",
                    "https://theozhang.me/meet/abc-defg-hjk?auto=1", " abc-defg-hjk\n"):
            self.assertEqual(room_id(ref), "abc-defg-hjk", ref)

    def test_bad(self):
        for ref in ("", "abc-defg", "abc-defg-hjkl", "abl-defg-hjk", "https://meet.caloogy.com/"):
            with self.assertRaises(Fail):
                room_id(ref)


class Links(unittest.TestCase):
    def ns(self, kind, url=None):
        return argparse.Namespace(tool=TOOLS[kind], url=url)

    def test_own_and_other_site(self):
        os.environ.pop("CALOOGY_MEET_URL", None)
        os.environ.pop("CALOOGY_CALL_URL", None)
        os.environ["XDG_CONFIG_HOME"] = "/nonexistent-caloogy-test"
        self.assertEqual(link(self.ns("meet"), "meet", "abc-defg-hjk"), "https://meet.caloogy.com/abc-defg-hjk")
        self.assertEqual(link(self.ns("meet"), "call", "abc-defg-hjk"), "https://call.caloogy.com/abc-defg-hjk")
        self.assertEqual(link(self.ns("call", "http://call.localhost:5095"), "call", "abc-defg-hjk"), "http://call.localhost:5095/abc-defg-hjk")


class Parser(unittest.TestCase):
    def test_json_either_side(self):
        for kind in ("meet", "call"):
            p = build_parser(TOOLS[kind])
            self.assertTrue(p.parse_args(["--json", "list"]).json)
            self.assertTrue(p.parse_args(["list", "--json"]).json)
            self.assertIs(p.parse_args(["new"]).tool, TOOLS[kind])

    def test_list_flags_exclusive(self):
        with self.assertRaises(SystemExit):
            build_parser(TOOLS["call"]).parse_args(["list", "--upcoming", "--recent"])

    def test_skills(self):
        for kind in ("meet", "call"):
            s = skill_text(TOOLS[kind])
            self.assertTrue(s.startswith(f"---\nname: caloogy-{kind}\n"))
            self.assertIsNone(re.search(r"\{(kind|Cap|site|what2?|whats|verb|video|Other|other|short)\}", s))


if __name__ == "__main__":
    unittest.main()
