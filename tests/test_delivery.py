"""Delivery strategies: toggles in the base branch, open branches for large alternatives."""

import os
import subprocess
import unittest

import support
from cadlib import document, miniyaml
from cadlib.spec import load
from test_verify import GitRepoCase, cad, git

MIXED = """\
feature: shop
dimensions:
  checkout:
    options: [one_page, multi_step]
    size: large
  theme: [light, dark]
verify:
  test: python3 check.py
  probe: python3 probe.py
"""


def files_on(repo, ref):
    return subprocess.run(["git", "ls-tree", "-r", "--name-only", ref], cwd=repo,
                          capture_output=True, text=True).stdout.split()


class StrategyRuleTest(unittest.TestCase):
    def strategy(self, **fields):
        raw = {"feature": "x", "dimensions": {"d": {"options": ["a", "b"], **fields}}}
        return load(raw).dimensions["d"].strategy[0]

    def test_rule(self):
        self.assertEqual(self.strategy(), "toggle")
        self.assertEqual(self.strategy(size="small"), "toggle")
        self.assertEqual(self.strategy(size="large"), "branch")
        self.assertEqual(self.strategy(size="large", coexist=True), "toggle")
        self.assertEqual(self.strategy(size="small", delivery="branch"), "branch")

    def test_invalid_fields(self):
        from cadlib.spec import SpecError
        with self.assertRaisesRegex(SpecError, "size must be small or large"):
            load({"feature": "x", "dimensions": {"d": {"options": ["a"], "size": "huge"}}})
        with self.assertRaisesRegex(SpecError, "did you mean 'one_page'"):
            load({"feature": "x", "dimensions": {"d": {"options": ["one_page", "b"], "decided": "one_pag"}}})


class PlanTest(unittest.TestCase):
    def test_open_branches_have_no_abstraction_and_hold(self):
        result = support.run_fixture("checkout-redesign.yaml")
        by_id = result.plan.by_id
        self.assertNotIn("dim.checkout", by_id)
        for nid in ("opt.checkout.one_page", "opt.checkout.multi_step"):
            self.assertTrue(by_id[nid].hold)
        # the interaction needs the one-page checkout, so it stays open too
        self.assertTrue(by_id["ix.upsell-one-page"].hold)
        self.assertIn("builds on `opt.checkout.one_page`", by_id["ix.upsell-one-page"].hold_reason)
        # toggles merge as usual
        self.assertFalse(by_id["opt.upsell.enabled"].hold)
        self.assertFalse(by_id["dim.payment_ui"].hold)

    def test_mergeable_work_never_sits_on_an_open_branch(self):
        result = support.run_fixture("checkout-redesign.yaml")
        by_id, placements = result.plan.by_id, result.stack.placements
        for nid, p in placements.items():
            if not by_id[nid].hold:
                cur = p.parent
                while cur is not None:
                    self.assertFalse(by_id[cur].hold, f"{nid} sits on open {cur}")
                    cur = placements[cur].parent

    def test_decided_branch_dimension_merges_the_winner(self):
        raw = support.load_fixture("checkout-redesign.yaml")
        raw["dimensions"]["checkout"]["decided"] = "one_page"
        result = support.run_raw(raw)
        self.assertEqual(result.space.theoretical, 4)
        self.assertFalse(result.plan.by_id["opt.checkout.one_page"].hold)
        self.assertNotIn("opt.checkout.multi_step", result.plan.by_id)
        self.assertFalse(result.plan.by_id["ix.upsell-one-page"].hold)


class MixedRepoCase(GitRepoCase):
    spec_text = MIXED

    def build(self, skip=()):
        self.node_branch("shop/base", "main")
        self.node_branch("shop/theme", "shop/base")
        self.node_branch("shop/theme-light", "shop/theme", ["opts/theme-light.txt"])
        self.node_branch("shop/theme-dark", "shop/theme", ["opts/theme-dark.txt"])
        for option in ("one_page", "multi_step"):
            branch = "shop/checkout-" + option.replace("_", "-")
            files = [] if option in skip else [f"opts/checkout-{option}.txt"]
            git(self.repo, "switch", "-q", "-c", branch, "shop/base")
            self.write("checkout.txt", option + "\n")  # the alternatives conflict on purpose
            for name in files:
                self.write(name, name + "\n")
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-qm", f"Add {option} checkout")
        git(self.repo, "switch", "-q", "main")


class VerifyOpenBranchesTest(MixedRepoCase):
    def test_alternatives_may_conflict_and_every_scenario_is_checked(self):
        self.build()
        code, data = self.verify("--integration", "--probe")
        self.assertEqual(code, 0, data)
        self.assertIn("integration: composed and checked 4 scenario(s) with their open branches", data["notes"])
        self.assertEqual(data["probe"], {"scenarios": 4, "failing": 0, "errors": 0})

    def test_unwired_alternative_is_caught_in_its_scenarios(self):
        self.build(skip=("one_page",))
        code, data = self.verify("--integration", "--probe")
        self.assertEqual(code, 1)
        issue = next(i for i in data["issues"] if i["check"] == "probe")
        self.assertEqual(issue["node"], "opt.checkout.one_page")
        self.assertIn("(T01, T02)", issue["text"])

    def test_missing_open_branch_skips_its_scenarios(self):
        self.build()
        git(self.repo, "branch", "-q", "-D", "shop/checkout-multi-step")
        code, data = self.verify("--integration", "--probe")
        self.assertEqual(code, 0, data)
        self.assertTrue(any("2 scenario(s) not checked yet" in n for n in data["notes"]))


class ComposeTest(MixedRepoCase):
    def test_compose_one_variant(self):
        self.build()
        proc = cad("compose", self.doc, "checkout=one_page", "theme=dark", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ok     shop/variant/one-page-dark", proc.stdout)
        self.assertIn("configure: theme=dark", proc.stdout)
        files = files_on(self.repo, "shop/variant/one-page-dark")
        self.assertIn("opts/checkout-one_page.txt", files)
        self.assertNotIn("opts/checkout-multi_step.txt", files)
        self.assertIn("opts/theme-light.txt", files)  # toggles are all merged; configuration picks
        current = subprocess.run(["git", "branch", "--show-current"], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(current.stdout.strip(), "main")

    def test_compose_all_and_recompose(self):
        self.build()
        proc = cad("compose", self.doc, "--all", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(proc.stdout.count("ok     shop/variant/"), 4)
        proc = cad("compose", self.doc, "T01", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_invalid_choice(self):
        self.build()
        proc = cad("compose", self.doc, "checkout=one_page", cwd=self.repo)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not a valid variant", proc.stderr)


class DecideTest(MixedRepoCase):
    def decide(self, dim, option):
        raw = miniyaml.loads(document.read(self.doc).spec_text)
        body = raw["dimensions"][dim]
        if isinstance(body, list):
            body = {"options": body}
        body["decided"] = option
        raw["dimensions"][dim] = body
        doc = document.read(self.doc)
        text = open(self.doc, encoding="utf-8").read().replace(doc.spec_text.rstrip("\n"), miniyaml.dumps(raw).rstrip("\n"), 1)
        with open(self.doc, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_deciding_an_open_decision_closes_the_losers(self):
        self.build()
        document.render(self.doc)
        self.decide("checkout", "one_page")
        result, _ = document.render(self.doc, note="Product picked the one-page checkout.")
        self.assertFalse(result.plan.by_id["opt.checkout.one_page"].hold)
        text = open(self.doc, encoding="utf-8").read()
        self.assertIn("Branches exist for nodes no longer planned: `opt.checkout.multi_step`", text)
        self.assertIn("decided: `one_page` (branch)", text)

    def test_deciding_a_built_toggle_plans_a_cleanup(self):
        self.build()
        document.render(self.doc)
        self.decide("theme", "dark")
        result, _ = document.render(self.doc, note="Dark theme only.")
        node = result.plan.by_id["cleanup.theme"]
        self.assertEqual(node.kind, "cleanup")
        self.assertIn("`light`", node.purpose)
        self.assertEqual(node.depends_on, ["opt.theme.dark"])


if __name__ == "__main__":
    unittest.main()
