"""Constraint handling and decision-space counting."""

import itertools
import unittest

from support import load_fixture, run_fixture, run_raw, spec_from
from cadlib import space as space_mod


def brute_force_valid(raw):
    """Independent oracle: plain itertools plus direct constraint checks."""
    spec = spec_from(raw)
    dims = list(spec.dimensions)
    out = []
    for combo in itertools.product(*(d.option_ids for d in spec.dimensions.values())):
        env = dict(zip(dims, combo))
        if all(c.holds(env) for c in spec.constraints):
            out.append(combo)
    return out


class LeadCaptureCountsTest(unittest.TestCase):
    def test_primary_example_counts(self):
        result = run_fixture("lead-capture-flow.yaml")
        s = result.space
        self.assertEqual(s.theoretical, 54)
        self.assertEqual(s.collapsed, 0)
        self.assertEqual(s.invalid, 12)
        self.assertEqual(len(s.valid), 42)
        self.assertEqual(s.theoretical, s.collapsed + s.invalid + len(s.valid))

    def test_constraint_reports(self):
        reports = {r.constraint.id: r for r in run_fixture("lead-capture-flow.yaml").space.reports}
        self.assertEqual((reports["C1"].removes_alone, reports["C1"].removes_only), (6, 6))
        self.assertEqual((reports["C2"].removes_alone, reports["C2"].removes_only), (6, 6))

    def test_matches_brute_force_oracle(self):
        raw = load_fixture("lead-capture-flow.yaml")
        self.assertEqual(run_raw(raw).space.valid, brute_force_valid(raw))

    def test_every_valid_variant_satisfies_constraints(self):
        result = run_fixture("lead-capture-flow.yaml")
        for v in result.space.valid:
            env = space_mod.variant_env(result.space.dims, v)
            self.assertTrue(all(c.holds(env) for c in result.spec.constraints), v)
            if env["pdf_delivery"] == "email":
                self.assertNotEqual(env["email_capture"], "disabled")
            if env["channel"] == "checkout":
                self.assertNotEqual(env["email_capture"], "before_test")


class AppliesWhenTest(unittest.TestCase):
    def test_conditional_dimension_collapses_duplicates(self):
        s = run_fixture("lead-capture-flow-html-email.yaml").space
        self.assertEqual(s.theoretical, 108)
        self.assertEqual(s.collapsed, 36)
        self.assertEqual(s.invalid, 20)
        self.assertEqual(len(s.valid), 52)
        idx = s.dims.index("email_format")
        pdf = s.dims.index("pdf_delivery")
        for v in s.valid:
            self.assertEqual(v[idx] is None, v[pdf] != "email")


class FindingsTest(unittest.TestCase):
    def setUp(self):
        self.result = run_fixture("findings.yaml")
        self.reports = {r.constraint.id: r for r in self.result.space.reports}

    def test_counts(self):
        s = self.result.space
        self.assertEqual((s.theoretical, s.invalid, len(s.valid)), (9, 4, 5))

    def test_dead_option(self):
        self.assertEqual(self.result.space.dead_options, {"channel": ["kiosk"]})
        self.assertTrue(any("Dead option in `channel`: `kiosk`" in f.text for f in self.result.findings))

    def test_redundant_and_never_firing_constraints(self):
        self.assertEqual(self.reports["no-kiosk"].finding, "")
        self.assertEqual(self.reports["C2"].finding, "redundant")
        self.assertEqual(self.reports["C3"].finding, "never fires")
        self.assertEqual(self.reports["C4"].finding, "")

    def test_single_option_dimension_warns(self):
        self.assertTrue(any("theme: only one option" in f.text for f in self.result.findings))

    def test_forced_dimension(self):
        result = run_raw({
            "feature": "forced",
            "dimensions": {"a": ["x", "y"], "b": ["p", "q"]},
            "constraints": [{"never": "b == q"}],
        })
        self.assertEqual(result.space.forced, {"b": "p"})
        self.assertEqual(result.space.dead_options, {"b": ["q"]})


class ContradictionTest(unittest.TestCase):
    def test_contradictory_constraints_are_an_error(self):
        result = run_fixture("contradictory.yaml")
        self.assertEqual(result.status, "error")
        self.assertEqual(result.space.valid, [])
        self.assertIsNone(result.plan)
        self.assertIn("contradict", result.errors[0].text)

    def test_rescuing_constraint_is_named(self):
        result = run_raw({
            "feature": "rescue",
            "dimensions": {"a": ["x", "y"]},
            "constraints": [{"never": "a == x"}, {"id": "too-strict", "never": "a == y"}],
        })
        self.assertEqual(result.space.rescuers, ["C1", "too-strict"])
        self.assertIn("Dropping C1 or too-strict", result.errors[0].text)

    def test_unreachable_interaction_warns(self):
        result = run_raw({
            "feature": "ix",
            "dimensions": {"a": ["x", "y"], "b": ["p", "q"]},
            "constraints": [{"if": "a == x", "requires": "b == p"}],
            "interactions": [{"id": "never", "when": "a == x and b == q", "title": "Never"}],
        })
        self.assertIn("never", result.space.unreachable_interactions)
        self.assertNotIn("ix.never", result.plan.by_id)


class LimitsTest(unittest.TestCase):
    def test_enumeration_is_refused_above_limit(self):
        raw = {
            "feature": "huge",
            "dimensions": {f"d{i}": [f"o{j}" for j in range(10)] for i in range(7)},
        }
        result = run_raw(raw)
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.space)
        self.assertIn("10,000,000 theoretical combinations exceed max_enumeration", result.errors[0].text)

    def test_primary_example_needs_confirmation(self):
        result = run_fixture("lead-capture-flow.yaml")
        self.assertEqual(result.status, "needs-confirmation")
        text = " ".join(result.confirmations)
        self.assertIn("42 targeted variants exceed max_valid_variants (20)", text)
        self.assertIn("13 implementation nodes exceed max_implementation_nodes (12)", text)
        self.assertIn("13 new MRs in this revision exceed require_confirmation_above (8)", text)
        self.assertEqual(result.suggestions[0], "proceed as planned")
        self.assertIn("switch the test matrix to pairwise", result.suggestions)

    def test_updates_only_count_new_nodes(self):
        first = run_fixture("lead-capture-flow.yaml")
        known = set(first.plan.by_id)
        second = run_fixture("lead-capture-flow-html-email.yaml", known_nodes=known)
        self.assertEqual(second.new_nodes, 4)
        self.assertFalse(any("require_confirmation_above" in c for c in second.confirmations))


if __name__ == "__main__":
    unittest.main()
