"""Combinatorial generation: exhaustive, pairwise, t-wise and selected."""

import itertools
import unittest

from support import load_fixture, run_raw
from cadlib.coverage import greedy_cover, tuples_of


def with_mode(name, **generation):
    raw = load_fixture(name)
    raw["generation"] = generation
    return raw


def reachable(valid, t):
    out = set()
    for v in valid:
        out.update(tuples_of(v, t))
    return out


class ModesTest(unittest.TestCase):
    def test_exhaustive_is_every_valid_variant(self):
        result = run_raw(with_mode("lead-capture-flow.yaml", mode="exhaustive"))
        self.assertEqual(result.scenarios.variants, result.space.valid)

    def test_pairwise_covers_every_reachable_pair(self):
        result = run_raw(with_mode("lead-capture-flow.yaml", mode="pairwise"))
        sc = result.scenarios
        self.assertLess(len(sc.variants), len(result.space.valid))
        self.assertEqual(reachable(sc.variants, 2), reachable(result.space.valid, 2))
        self.assertEqual(sc.covered, sc.coverable)
        self.assertTrue(set(sc.variants) <= set(result.space.valid))
        # Pairs ruled out by constraints are counted, never silently dropped.
        self.assertEqual(sc.possible - sc.coverable, sc.excluded)
        self.assertGreater(sc.excluded, 0)

    def test_pairwise_is_deterministic(self):
        a = run_raw(with_mode("lead-capture-flow.yaml", mode="pairwise")).scenarios.variants
        b = run_raw(with_mode("lead-capture-flow.yaml", mode="pairwise")).scenarios.variants
        self.assertEqual(a, b)

    def test_pairwise_size_for_primary_example(self):
        # The largest pair space is channel x pdf_delivery (9 pairs), so 9 is a lower bound.
        result = run_raw(with_mode("lead-capture-flow.yaml", mode="pairwise"))
        self.assertGreaterEqual(len(result.scenarios.variants), 9)
        self.assertLessEqual(len(result.scenarios.variants), 12)

    def test_twise_three_covers_every_reachable_triple(self):
        result = run_raw(with_mode("lead-capture-flow.yaml", mode="twise", strength=3))
        sc = result.scenarios
        self.assertEqual(reachable(sc.variants, 3), reachable(result.space.valid, 3))
        pairwise = run_raw(with_mode("lead-capture-flow.yaml", mode="pairwise")).scenarios
        self.assertGreater(len(sc.variants), len(pairwise.variants))

    def test_twise_with_conditional_dimension(self):
        result = run_raw(with_mode("lead-capture-flow-html-email.yaml", mode="pairwise"))
        sc = result.scenarios
        self.assertEqual(reachable(sc.variants, 2), reachable(result.space.valid, 2))
        formats = {v[4] for v in sc.variants}
        self.assertEqual(formats, {None, "html", "text"})

    def test_selected_variants(self):
        raw = with_mode("lead-capture-flow.yaml", mode="selected", variants=[
            {"channel": "website", "pdf_delivery": "email", "email_capture": "before_test", "crm_sync": "hubspot"},
            {"channel": "checkout", "pdf_delivery": "none", "email_capture": "disabled", "crm_sync": "none"},
        ])
        result = run_raw(raw)
        self.assertEqual(len(result.scenarios.variants), 2)
        self.assertNotIn("opt.channel.landing_page", result.plan.by_id)
        self.assertNotIn("opt.pdf_delivery.download", result.plan.by_id)
        self.assertIn("opt.crm_sync.hubspot", result.plan.by_id)
        self.assertIn("landing_page", result.plan.out_of_scope["channel"])

    def test_selected_variants_are_validated(self):
        raw = with_mode("lead-capture-flow.yaml", mode="selected", variants=[
            {"channel": "checkout", "pdf_delivery": "none", "email_capture": "before_test", "crm_sync": "none"},
            {"channel": "website", "pdf_delivery": "email", "crm_sync": "none"},
            {"channel": "web", "pdf_delivery": "email", "email_capture": "after_test", "crm_sync": "none"},
        ])
        result = run_raw(raw)
        self.assertEqual(result.status, "error")
        text = " ".join(f.text for f in result.errors)
        self.assertIn("violates C2", text)
        self.assertIn("missing a choice for email_capture", text)
        self.assertIn("unknown option(s) channel=web", text)


class GreedyCoverTest(unittest.TestCase):
    def test_classic_three_binary_parameters(self):
        variants = list(itertools.product("ab", "cd", "ef"))
        chosen = greedy_cover(variants, 2)
        covered = set()
        for i in chosen:
            covered.update(tuples_of(variants[i], 2))
        self.assertEqual(covered, reachable(variants, 2))
        self.assertLessEqual(len(chosen), 6)

    def test_strength_equal_to_dimensions_needs_everything(self):
        variants = list(itertools.product("ab", "cd"))
        self.assertEqual(greedy_cover(variants, 2), [0, 1, 2, 3])

    def test_scales_to_a_mid_sized_space(self):
        variants = list(itertools.product(*[range(4)] * 6))  # 4096 variants
        chosen = greedy_cover(variants, 2)
        covered = set()
        for i in chosen:
            covered.update(tuples_of(variants[i], 2))
        self.assertEqual(covered, reachable(variants, 2))
        self.assertLess(len(chosen), 40)


if __name__ == "__main__":
    unittest.main()
