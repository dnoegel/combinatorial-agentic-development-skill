import unittest

from support import load_fixture
from cadlib.spec import SpecError, humanize, load, spec_hash


def base(**extra):
    raw = {"feature": "demo", "dimensions": {"a": ["x", "y"], "b": ["p", "none"]}}
    raw.update(extra)
    return raw


class LoadTest(unittest.TestCase):
    def test_primary_fixture_loads_with_project_alias(self):
        spec = load(load_fixture("lead-capture-flow.yaml"))
        self.assertEqual(spec.feature, "lead-capture-flow")
        self.assertEqual(spec.title, "Lead capture flow")
        self.assertEqual(list(spec.dimensions), ["channel", "pdf_delivery", "email_capture", "crm_sync"])
        self.assertEqual(len(spec.constraints), 2)
        self.assertEqual(spec.limits["max_valid_variants"], 20)
        self.assertEqual(spec.limits["max_enumeration"], 100000)

    def test_noop_defaults_and_overrides(self):
        raw = base()
        raw["dimensions"]["c"] = [{"id": "off"}, {"id": "on"}, {"id": "manual", "noop": True}]
        spec = load(raw)
        self.assertTrue(spec.dimensions["b"].option("none").noop)
        self.assertTrue(spec.dimensions["c"].option("off").noop)
        self.assertFalse(spec.dimensions["c"].option("on").noop)
        self.assertTrue(spec.dimensions["c"].option("manual").noop)

    def test_long_form_dimension(self):
        raw = base()
        raw["dimensions"]["c"] = {"label": "Colour", "options": {"red": {"label": "Red!"}, "blue": None}, "bundle": True}
        spec = load(raw)
        dim = spec.dimensions["c"]
        self.assertEqual(dim.label, "Colour")
        self.assertEqual(dim.option_ids, ["red", "blue"])
        self.assertEqual(dim.option("red").label, "Red!")
        self.assertTrue(dim.bundle)

    def test_constraint_forms(self):
        spec = load(base(constraints=[
            {"if": "a == x", "requires": "b == p"},
            {"if": "a == y", "excludes": "b == p"},
            {"never": "a == x and b == none", "id": "X1", "reason": "because"},
            "a == y and b == none",
        ]))
        self.assertEqual([c.kind for c in spec.constraints], ["requires", "excludes", "never", "never"])
        self.assertEqual(spec.constraints[2].id, "X1")
        self.assertEqual(spec.constraints[2].reason, "because")
        self.assertEqual(spec.constraints[0].text, "if a == x requires b == p")

    def test_errors_are_collected_with_suggestions(self):
        with self.assertRaises(SpecError) as ctx:
            load({
                "feature": "Bad Name",
                "dimensions": {"a": ["x", "x"], "b": []},
                "constraints": [{"if": "a == z", "requires": "c == q"}, {"iff": "a == x", "requires": "a == x"}],
                "generation": {"mode": "pairwize"},
            })
        text = "\n".join(ctx.exception.errors)
        self.assertIn("'bad-name'", text)
        self.assertIn("duplicate option 'x'", text)
        self.assertIn("b: needs at least one option", text)
        self.assertIn("unknown option 'z'", text)
        self.assertIn("unknown dimension 'c'", text)
        self.assertIn("did you mean 'if'", text)
        self.assertIn("did you mean 'pairwise'", text)

    def test_applies_when_must_reference_earlier_dimensions(self):
        raw = {"feature": "demo", "dimensions": {
            "a": {"options": ["x", "y"], "applies_when": "b == p"},
            "b": ["p", "q"],
        }}
        with self.assertRaisesRegex(SpecError, "listed above"):
            load(raw)

    def test_generation_modes(self):
        self.assertEqual(load(base(generation={"mode": "pairwise"})).strength, 2)
        self.assertEqual(load(base(generation={"mode": "twise"}, dimensions={"a": ["x"], "b": ["y"], "c": ["z", "w"]})).strength, 3)
        with self.assertRaisesRegex(SpecError, "larger than the number of dimensions"):
            load(base(generation={"mode": "twise", "strength": 3}))
        with self.assertRaisesRegex(SpecError, "needs `generation.variants`"):
            load(base(generation={"mode": "selected"}))

    def test_bad_limits(self):
        with self.assertRaisesRegex(SpecError, "positive integer"):
            load(base(limits={"max_valid_variants": 0}))

    def test_unknown_keys_warn(self):
        spec = load(base(dimension_notes="x", limits={"max_variants": 3}))
        self.assertTrue(any("dimension_notes" in w for w in spec.warnings))
        self.assertTrue(any("max_variants" in w for w in spec.warnings))


class HelpersTest(unittest.TestCase):
    def test_humanize(self):
        self.assertEqual(humanize("pdf_delivery"), "PDF delivery")
        self.assertEqual(humanize("crm_sync"), "CRM sync")
        self.assertEqual(humanize("landing-page"), "Landing page")

    def test_hash_ignores_formatting(self):
        self.assertEqual(spec_hash({"a": 1, "b": [1, 2]}), spec_hash({"b": [1, 2], "a": 1}))
        self.assertNotEqual(spec_hash({"a": 1}), spec_hash({"a": 2}))


if __name__ == "__main__":
    unittest.main()
