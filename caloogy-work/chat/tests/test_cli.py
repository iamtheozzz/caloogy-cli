import argparse
import unittest

from caloogy_chat.cli import Ctx, Fail, att_text, attachment, build_parser, find_conv, find_person


def ctx(convs, users, friends=()):
    c = Ctx.__new__(Ctx)
    c.args, c.me, c.convs, c.users = None, {"id": "aaaaaaa1", "name": "Alice"}, convs, users
    c._friends = {i: users[i] for i in friends}
    return c


USERS = {"aaaaaaa1": {"name": "Alice"}, "bbbbbbb2": {"name": "Bob Lee"}, "ccccccc3": {"name": "Bob Ray"}, "ddddddd4": {"name": "Dana"}}
CONVS = [
    {"id": "111111111111", "kind": "dm", "members": ["aaaaaaa1", "bbbbbbb2"]},
    {"id": "222222222222", "kind": "group", "name": "Design", "members": ["aaaaaaa1", "bbbbbbb2", "ccccccc3"]},
    {"id": "333333333333", "kind": "dm", "members": ["aaaaaaa1", "ccccccc3"]},
]


class Find(unittest.TestCase):
    def test_by_id_name_group(self):
        c = ctx(CONVS, USERS)
        self.assertEqual(find_conv(c, "111111111111")["id"], "111111111111")
        self.assertEqual(find_conv(c, "bob lee")["id"], "111111111111")
        self.assertEqual(find_conv(c, "bbbbbbb2")["id"], "111111111111")
        self.assertEqual(find_conv(c, "design")["id"], "222222222222")
        self.assertEqual(find_conv(c, "Ray")["id"], "333333333333")      # unique part of a name

    def test_ambiguous_and_missing(self):
        c = ctx(CONVS, USERS, friends=["ddddddd4"])
        with self.assertRaises(Fail) as e:
            find_conv(c, "Bob")
        self.assertIn("bbbbbbb2", str(e.exception))
        with self.assertRaises(Fail):
            find_conv(c, "999999999999")
        with self.assertRaises(Fail):
            find_conv(c, "Dana")                                       # a friend, but no chat yet and not creating
        with self.assertRaises(Fail):
            find_person(c, "Zed")

    def test_me(self):
        self.assertEqual(find_person(ctx(CONVS, USERS), "me"), "aaaaaaa1")


class Attach(unittest.TestCase):
    def ns(self, **kw):
        return argparse.Namespace(**{"call": None, "doc": None, "link": None, "title": None, **kw})

    def test_call(self):
        self.assertEqual(attachment(self.ns(call="https://call.caloogy.com/abc-defg-hjk")),
                         {"kind": "call", "mode": "call", "room": "abc-defg-hjk"})
        self.assertEqual(attachment(self.ns(call="https://meet.caloogy.com/abc-defg-hjk?x=1"))["mode"], "meet")
        with self.assertRaises(Fail):
            attachment(self.ns(call="https://example.com/abc-defg-hjk"))

    def test_doc_and_link(self):
        a = attachment(self.ns(doc="https://docs.caloogy.com/2583df90/3f9c0a1b2d4e5f60", title="Plan"))
        self.assertEqual(a, {"kind": "doc", "owner": "2583df90", "id": "3f9c0a1b2d4e5f60", "title": "Plan"})
        self.assertEqual(attachment(self.ns(link="https://x.org/a"))["url"], "https://x.org/a")
        with self.assertRaises(Fail):
            attachment(self.ns(link="ftp://x"))
        with self.assertRaises(Fail):
            attachment(self.ns(link="https://x.org", doc="https://docs.caloogy.com/2583df90/3f9c0a1b2d4e5f60"))
        self.assertIsNone(attachment(self.ns()))

    def test_text(self):
        self.assertEqual(att_text({"kind": "call", "mode": "meet", "room": "abc-defg-hjk"}), "[video meeting] https://meet.caloogy.com/abc-defg-hjk")


class Parser(unittest.TestCase):
    def test_json_either_side(self):
        p = build_parser()
        self.assertTrue(p.parse_args(["--json", "list"]).json)
        self.assertTrue(p.parse_args(["list", "--json"]).json)

    def test_read_flags_exclusive(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["read", "Bob", "-n", "5", "--all"])


if __name__ == "__main__":
    unittest.main()
