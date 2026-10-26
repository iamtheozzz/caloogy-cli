import unittest

from caloogy_docs.cli import Fail, build_parser, doc_id, replace_once


class DocId(unittest.TestCase):
    def test_forms(self):
        for ref in ("3f9c0a1b2d4e5f60", "2583df90/3f9c0a1b2d4e5f60", "https://docs.caloogy.com/2583df90/3f9c0a1b2d4e5f60",
                    "https://docs.caloogy.com/2583df90/3F9C0A1B2D4E5F60/", "https://docs.caloogy.com/2583df90/3f9c0a1b2d4e5f60?embed=1"):
            self.assertEqual(doc_id(ref), "3f9c0a1b2d4e5f60", ref)

    def test_bad(self):
        for ref in ("", "2583df90", "3f9c0a1b2d4e5f6", "3f9c0a1b2d4e5f600", "https://docs.caloogy.com/"):
            with self.assertRaises(Fail):
                doc_id(ref)


class Replace(unittest.TestCase):
    def test_once(self):
        self.assertEqual(replace_once("a teh b", "teh", "the", False), ("a the b", 1))

    def test_delete(self):
        self.assertEqual(replace_once("keep\ndrop\n", "drop\n", "", False), ("keep\n", 1))

    def test_missing_and_ambiguous(self):
        with self.assertRaises(Fail):
            replace_once("abc", "x", "y", False)
        with self.assertRaises(Fail):
            replace_once("x x", "x", "y", False)
        with self.assertRaises(Fail):
            replace_once("x", "", "y", False)

    def test_all(self):
        self.assertEqual(replace_once("x x", "x", "y", True), ("y y", 2))


class Parser(unittest.TestCase):
    def test_json_either_side(self):
        p = build_parser()
        self.assertTrue(p.parse_args(["--json", "list"]).json)
        self.assertTrue(p.parse_args(["list", "--json"]).json)

    def test_list_flags_exclusive(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["list", "--mine", "--shared"])


if __name__ == "__main__":
    unittest.main()
