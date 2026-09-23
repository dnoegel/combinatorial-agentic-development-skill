import glob
import os
import unittest

from support import FIXTURES
from cadlib.miniyaml import YamlError, dumps, loads

try:
    import yaml  # PyYAML is optional; used only to cross-check the fixtures.
except ImportError:  # pragma: no cover
    yaml = None


class LoadsTest(unittest.TestCase):
    def test_block_mapping_and_sequence(self):
        self.assertEqual(
            loads("a: 1\nb:\n  - x\n  - y\nc:\n  d: true\n"),
            {"a": 1, "b": ["x", "y"], "c": {"d": True}},
        )

    def test_sequence_at_same_indent_as_key(self):
        self.assertEqual(loads("a:\n- x\n- y\n"), {"a": ["x", "y"]})

    def test_list_of_mappings(self):
        text = "items:\n  - if: a == b\n    requires: c != d\n  - never: x == y\n"
        self.assertEqual(
            loads(text),
            {"items": [{"if": "a == b", "requires": "c != d"}, {"never": "x == y"}]},
        )

    def test_flow_collections(self):
        self.assertEqual(loads("a: [x, 'y z', \"w\"]\nb: {k: v, n: 2}\n"), {"a": ["x", "y z", "w"], "b": {"k": "v", "n": 2}})

    def test_plain_scalars_follow_yaml_1_2_core(self):
        self.assertEqual(
            loads("a: none\nb: off\nc: no\nd: null\ne: ~\nf: 1.5\ng: -3\nh: False\n"),
            {"a": "none", "b": "off", "c": "no", "d": None, "e": None, "f": 1.5, "g": -3, "h": False},
        )

    def test_comments_are_ignored_outside_quotes(self):
        self.assertEqual(loads("# head\na: b # tail\nc: 'x # y'\n"), {"a": "b", "c": "x # y"})

    def test_expression_with_brackets_stays_a_string(self):
        self.assertEqual(loads("if: channel in [web, app]\n"), {"if": "channel in [web, app]"})

    def test_block_scalars(self):
        text = "a: |\n  line one\n  line two\nb: >-\n  folded\n  text\nc: x\n"
        self.assertEqual(loads(text), {"a": "line one\nline two\n", "b": "folded text", "c": "x"})

    def test_empty_document(self):
        self.assertIsNone(loads("# nothing\n\n"))

    def test_errors_carry_line_numbers(self):
        with self.assertRaises(YamlError) as ctx:
            loads("a: 1\na: 2\n")
        self.assertIn("line 2", str(ctx.exception))
        with self.assertRaises(YamlError):
            loads("a:\n  - x\n  y: 1\n")
        with self.assertRaises(YamlError):
            loads("a: &anchor 1\n")
        with self.assertRaises(YamlError):
            loads("a:\n\tb: 1\n")

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_fixtures_match_pyyaml(self):
        for path in glob.glob(os.path.join(FIXTURES, "*.yaml")):
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(loads(text), yaml.safe_load(text))


class DumpsTest(unittest.TestCase):
    def test_round_trip(self):
        value = {
            "cad": 1,
            "status": "draft",
            "approved": {"by": "Dana", "on": "2026-09-23", "hash": "abc"},
            "nodes": {"opt.a.b": {"branch": "x/a-b", "mr": "!12", "status": "mr-open"}},
            "list": [{"a": 1, "b": [1, 2]}, "plain", ""],
            "empty": {},
            "tricky": ["yes: no", "#hash", "true", "12", " padded", "- dash"],
        }
        self.assertEqual(loads(dumps(value)), value)


if __name__ == "__main__":
    unittest.main()
