import unittest

import support  # noqa: F401
from cadlib.expr import And, Atom, ExprError, Not, Or, parse, validate

DIMS = {"channel": ["web", "app", "kiosk"], "login": ["password", "sso", "none"]}


class ParseTest(unittest.TestCase):
    def test_atoms(self):
        self.assertEqual(parse("channel == web"), Atom("channel", "==", ("web",)))
        self.assertEqual(parse("channel != web"), Atom("channel", "!=", ("web",)))
        self.assertEqual(parse("channel in [web, app]"), Atom("channel", "in", ("web", "app")))
        self.assertEqual(parse("channel not in [kiosk]"), Atom("channel", "not in", ("kiosk",)))

    def test_precedence_and_parentheses(self):
        node = parse("channel == web or channel == app and login == sso")
        self.assertIsInstance(node, Or)
        self.assertIsInstance(node.items[1], And)
        node = parse("not (channel == web or login == sso)")
        self.assertIsInstance(node, Not)

    def test_round_trip_text(self):
        for text in ("channel == web", "channel in [web, app]", "channel == web and login != none"):
            self.assertEqual(str(parse(text)), text)

    def test_syntax_errors_are_helpful(self):
        with self.assertRaisesRegex(ExprError, "use '=='"):
            parse("channel = web")
        with self.assertRaises(ExprError):
            parse("channel ==")
        with self.assertRaises(ExprError):
            parse("(channel == web")
        with self.assertRaises(ExprError):
            parse("channel == web extra")
        with self.assertRaises(ExprError):
            parse("")

    def test_never_evaluates_code(self):
        with self.assertRaises(ExprError):
            parse("__import__('os').system('true')")


class EvaluateTest(unittest.TestCase):
    def test_semantics(self):
        env = {"channel": "web", "login": "sso"}
        self.assertTrue(parse("channel == web and login in [sso, password]").evaluate(env))
        self.assertFalse(parse("channel not in [web]").evaluate(env))
        self.assertTrue(parse("not login == none").evaluate(env))

    def test_missing_dimension_has_no_value(self):
        env = {"channel": "web", "login": None}
        self.assertFalse(parse("login == sso").evaluate(env))
        self.assertFalse(parse("login in [sso]").evaluate(env))
        self.assertTrue(parse("login != sso").evaluate(env))
        self.assertTrue(parse("login not in [sso]").evaluate(env))


class ValidateTest(unittest.TestCase):
    def test_unknown_names_get_suggestions(self):
        problems = validate(parse("chanel == web and login == ssoo"), DIMS)
        self.assertEqual(len(problems), 2)
        self.assertIn("did you mean 'channel'", problems[0])
        self.assertIn("did you mean 'sso'", problems[1])

    def test_valid_expression_has_no_problems(self):
        self.assertEqual(validate(parse("channel in [web, app]"), DIMS), [])


if __name__ == "__main__":
    unittest.main()
