"""Implementation nodes, dependencies and stack placement."""

import unittest

from support import load_fixture, run_fixture, run_raw
from cadlib.stack import branch_slug, steps

REQUIRED_FIELDS = (
    "id", "title", "purpose", "decisions", "scope", "depends_on", "components", "files",
    "guidance", "tests", "acceptance", "risk", "complexity",
)


class NodesTest(unittest.TestCase):
    def setUp(self):
        self.result = run_fixture("lead-capture-flow.yaml")
        self.plan = self.result.plan

    def test_nodes_follow_options_not_variants(self):
        ids = [n.id for n in self.plan.nodes]
        self.assertEqual(len(ids), 13)
        self.assertEqual(ids[:5], ["base", "dim.channel", "dim.pdf_delivery", "dim.email_capture", "dim.crm_sync"])
        self.assertIn("opt.pdf_delivery.email", ids)
        # No-op options live inside their abstraction instead of getting an MR.
        self.assertNotIn("opt.pdf_delivery.none", ids)
        self.assertNotIn("opt.email_capture.disabled", ids)
        self.assertNotIn("opt.crm_sync.none", ids)

    def test_requires_constraint_creates_a_dependency(self):
        node = self.plan.by_id["opt.pdf_delivery.email"]
        self.assertEqual(sorted(node.depends_on), ["dim.email_capture", "dim.pdf_delivery"])
        self.assertIn("constraint C1", node.notes_derived[0])

    def test_requiring_an_exact_option_builds_on_that_option(self):
        result = run_raw({
            "feature": "homepage",
            "dimensions": {
                "rendering": ["static", "dynamic"],
                "guestbook": {"options": ["enabled", "none"], "bundle": True},
            },
            "constraints": [{"if": "guestbook == enabled", "requires": "rendering == dynamic"}],
        })
        self.assertEqual(result.plan.by_id["dim.guestbook"].depends_on, ["opt.rendering.dynamic"])
        self.assertEqual(result.stack.placements["dim.guestbook"].parent, "opt.rendering.dynamic")

    def test_excludes_constraint_creates_no_dependency(self):
        self.assertEqual(self.plan.by_id["opt.channel.checkout"].depends_on, ["dim.channel"])

    def test_every_node_has_the_required_fields(self):
        for node in self.plan.nodes:
            for field in REQUIRED_FIELDS:
                self.assertTrue(hasattr(node, field), f"{node.id} lacks {field}")
            self.assertTrue(node.title and node.purpose and node.scope and node.tests and node.acceptance)
            self.assertIn(node.risk, ("low", "medium", "high"))
            self.assertIn(node.complexity, ("S", "M", "L"))

    def test_scenarios_per_option(self):
        email = self.plan.by_id["opt.pdf_delivery.email"]
        self.assertEqual(len(email.scenarios), 10)
        self.assertEqual(len(self.plan.by_id["base"].scenarios), 42)

    def test_configurable_count(self):
        self.assertEqual(self.plan.configurable, 42)


class ConditionalAndInteractionTest(unittest.TestCase):
    def setUp(self):
        self.plan = run_fixture("lead-capture-flow-html-email.yaml").plan

    def test_applies_when_depends_on_enabling_option(self):
        self.assertEqual(self.plan.by_id["dim.email_format"].depends_on, ["opt.pdf_delivery.email"])

    def test_interaction_depends_on_both_options(self):
        node = self.plan.by_id["ix.pdf-after-capture"]
        self.assertEqual(sorted(node.depends_on), ["opt.email_capture.after_test", "opt.pdf_delivery.email"])
        self.assertEqual(node.risk, "high")


class BundleAndEnrichmentTest(unittest.TestCase):
    def test_bundle_folds_options_into_one_node(self):
        raw = load_fixture("lead-capture-flow.yaml")
        raw["dimensions"]["crm_sync"] = {"options": ["hubspot", "none"], "bundle": True}
        raw["dimensions"]["channel"] = {"options": ["website", "landing_page", "checkout"], "bundle": True}
        plan = run_raw(raw).plan
        self.assertEqual(len(plan.nodes), 9)
        self.assertNotIn("opt.crm_sync.hubspot", plan.by_id)
        self.assertIn("website", plan.by_id["dim.channel"].title)

    def test_plan_enrichment_is_applied(self):
        raw = load_fixture("lead-capture-flow.yaml")
        raw["plan"] = {
            "base": {"title": "Add lead-capture domain model", "files": ["src/leads/model.ts"], "components": "leads"},
            "opt.nope": {"title": "x"},
        }
        result = run_raw(raw)
        base = result.plan.by_id["base"]
        self.assertEqual(base.title, "Add lead-capture domain model")
        self.assertEqual(base.files, ["src/leads/model.ts"])
        self.assertEqual(base.components, ["leads"])
        self.assertTrue(any("plan.opt.nope" in f.text for f in result.findings))


class StackTest(unittest.TestCase):
    def test_tree_layout_for_primary_example(self):
        stack = run_fixture("lead-capture-flow.yaml").stack
        parent = {n: p.parent for n, p in stack.placements.items()}
        self.assertIsNone(parent["base"])
        self.assertEqual(parent["dim.channel"], "base")
        self.assertEqual(parent["dim.email_capture"], "base")
        # PDF delivery by email needs email capture, so its lane is grafted there.
        self.assertEqual(parent["dim.pdf_delivery"], "dim.email_capture")
        self.assertEqual(stack.placements["dim.pdf_delivery"].grafted_for, "opt.pdf_delivery.email")
        self.assertEqual(parent["opt.pdf_delivery.email"], "dim.pdf_delivery")
        self.assertEqual(parent["opt.crm_sync.hubspot"], "dim.crm_sync")
        self.assertEqual(stack.waves, 1)
        self.assertEqual(stack.placements["opt.channel.website"].branch, "lead-capture-flow/channel-website")

    def test_every_dependency_is_an_ancestor(self):
        for name in ("lead-capture-flow.yaml", "lead-capture-flow-html-email.yaml"):
            result = run_fixture(name)
            stack = result.stack
            for node in result.plan.nodes:
                chain, cur = set(), stack.placements[node.id].parent
                while cur is not None:
                    chain.add(cur)
                    cur = stack.placements[cur].parent
                for dep in node.depends_on:
                    covered = dep in chain or stack.placements[dep].wave < stack.placements[node.id].wave
                    self.assertTrue(covered, f"{name}: {node.id} misses {dep}")

    def test_parents_come_first_in_order(self):
        stack = run_fixture("lead-capture-flow-html-email.yaml").stack
        seen = set()
        for nid in stack.order:
            parent = stack.placements[nid].parent
            self.assertTrue(parent is None or parent in seen)
            seen.add(nid)

    def test_linear_layout(self):
        raw = load_fixture("lead-capture-flow.yaml")
        raw["stack"] = {"layout": "linear"}
        result = run_raw(raw)
        order = result.stack.order
        self.assertEqual(order, result.plan.order)
        for prev, nxt in zip(order, order[1:]):
            self.assertEqual(result.stack.placements[nxt].parent, prev)
        self.assertEqual(result.stack.lanes, 1)

    def test_started_lanes_are_never_moved(self):
        state = {
            "base": {"status": "merged"},
            "dim.email_capture": {"status": "merged"},
            "opt.email_capture.after_test": {"status": "mr-open", "mr": "!7"},
        }
        result = run_fixture("lead-capture-flow-html-email.yaml", state=state)
        placements = result.stack.placements
        self.assertEqual(placements["opt.email_capture.after_test"].parent, "dim.email_capture")
        ix = placements["ix.pdf-after-capture"]
        self.assertIn(ix.parent, ("opt.email_capture.after_test", None))
        if ix.parent is None:
            self.assertEqual(ix.wave, 1)

    def test_wave_fallback_when_lanes_cannot_be_grafted(self):
        state = {
            "opt.pdf_delivery.email": {"status": "mr-open"},
            "opt.email_capture.after_test": {"status": "mr-open"},
        }
        result = run_fixture("lead-capture-flow-html-email.yaml", state=state)
        ix = result.stack.placements["ix.pdf-after-capture"]
        self.assertIsNone(ix.parent)
        self.assertEqual(ix.wave, 1)
        self.assertEqual(sorted(ix.waits_for), ["opt.email_capture.after_test", "opt.pdf_delivery.email"])
        self.assertTrue(any("wave 2" in f.text for f in result.findings))

    def test_branch_slugs(self):
        self.assertEqual(branch_slug("base"), "base")
        self.assertEqual(branch_slug("dim.pdf_delivery"), "pdf-delivery")
        self.assertEqual(branch_slug("opt.pdf_delivery.email"), "pdf-delivery-email")
        self.assertEqual(branch_slug("ix.Send_PDF"), "send-pdf")


class StepsTest(unittest.TestCase):
    def test_dry_run_steps(self):
        result = run_fixture("lead-capture-flow.yaml")
        out = steps(result.plan, result.stack, {})
        self.assertEqual(out[0]["commands"][0], "git switch -c lead-capture-flow/base origin/main")
        self.assertEqual(out[0]["commands"][1], "git update-ref refs/cad/base/lead-capture-flow/base origin/main")
        child = next(s for s in out if s["node"] == "dim.pdf_delivery")
        self.assertEqual(child["commands"][0], "git switch -c lead-capture-flow/pdf-delivery lead-capture-flow/email-capture")
        for s in out:
            self.assertFalse(any(c.startswith(("glab", "gh ", "git push")) for c in s["commands"]))

    def test_children_of_merged_parents_start_from_the_base_branch(self):
        result = run_fixture("lead-capture-flow.yaml")
        state = {"base": {"status": "merged"}, "dim.channel": {"status": "branched"}}
        out = {s["node"]: s for s in steps(result.plan, result.stack, state, remote=False)}
        self.assertEqual(out["base"]["commands"], [])
        self.assertEqual(out["dim.channel"]["commands"], [])
        self.assertEqual(out["dim.crm_sync"]["commands"][0], "git switch -c lead-capture-flow/crm-sync main")


if __name__ == "__main__":
    unittest.main()
