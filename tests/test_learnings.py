"""Regression tests for findings from a real run: coupling, pins, titles and hygiene warnings."""

import os
import subprocess
import unittest

import support  # noqa: F401  (puts cadlib on the path)
from test_verify import GitRepoCase, git

HOMEPAGE = {
    "feature": "homepage",
    "dimensions": {
        "style": ["serious", "funny"],
        "imprint": ["enabled", "none"],
        "start_page": {"options": [
            {"id": "about_me", "label": "About me"},
            {"id": "company", "label": "My company (Shopware)"},
            {"id": "news", "label": "News"},
        ]},
    },
    "constraints": [{"if": "start_page == company", "requires": "imprint == enabled"}],
}


def chain(stack, nid):
    out = []
    cur = stack.placements[nid].parent
    while cur is not None:
        out.append(cur)
        cur = stack.placements[cur].parent
    return out


class CouplingTest(unittest.TestCase):
    def test_only_the_node_that_needs_both_lanes_is_coupled(self):
        result = support.run_raw(HOMEPAGE)
        stack = result.stack
        # The small imprint lane moves under the start page abstraction ...
        self.assertEqual(stack.placements["dim.imprint"].parent, "dim.start_page")
        self.assertEqual(stack.placements["opt.start_page.company"].parent, "opt.imprint.enabled")
        # ... so the other start pages do not carry imprint code.
        for nid in ("opt.start_page.about_me", "opt.start_page.news"):
            self.assertEqual(stack.placements[nid].parent, "dim.start_page")
            self.assertFalse({"dim.imprint", "opt.imprint.enabled"} & set(chain(stack, nid)))

    def test_expensive_grafts_lose_to_a_later_wave(self):
        state = {
            "base": {"status": "merged"},
            "dim.email_capture": {"status": "merged"},
            "opt.email_capture.after_test": {"status": "mr-open"},
        }
        result = support.run_fixture("lead-capture-flow-html-email.yaml", state=state)
        ix = result.stack.placements["ix.pdf-after-capture"]
        self.assertIsNone(ix.parent)
        self.assertEqual(ix.wave, 1)
        self.assertEqual(result.stack.placements["dim.pdf_delivery"].parent, "base")

    def test_max_coupling_is_configurable(self):
        raw = support.load_fixture("lead-capture-flow-html-email.yaml")
        self.assertIsNotNone(support.run_raw(raw).stack.placements["ix.pdf-after-capture"].parent)
        raw["stack"] = {"max_coupling": 0}
        placements = support.run_raw(raw).stack.placements
        self.assertEqual([p.node for p in placements.values() if p.grafted_for], [])
        self.assertGreaterEqual(placements["ix.pdf-after-capture"].wave, 1)


class PinTest(unittest.TestCase):
    def test_started_branches_keep_their_recorded_parent(self):
        # Built with an older layout: the whole start page lane on the enabled imprint.
        state = {
            "dim.start_page": {"status": "branched", "onto": "homepage/imprint-enabled"},
            "opt.imprint.enabled": {"status": "branched", "onto": "homepage/imprint"},
            "dim.imprint": {"status": "branched", "onto": "homepage/base"},
            "base": {"status": "branched", "onto": "main"},
        }
        placements = support.run_raw(HOMEPAGE, state=state).stack.placements
        self.assertEqual(placements["dim.start_page"].parent, "opt.imprint.enabled")
        self.assertEqual(placements["dim.imprint"].parent, "base")

    def test_invalid_pins_are_ignored(self):
        state = {"opt.start_page.company": {"status": "branched", "onto": "homepage/style"}}
        placements = support.run_raw(HOMEPAGE, state=state).stack.placements
        self.assertEqual(placements["opt.start_page.company"].parent, "opt.imprint.enabled")


class TitleTest(unittest.TestCase):
    def test_option_titles_keep_proper_nouns_and_acronyms(self):
        plan = support.run_raw(HOMEPAGE).plan
        self.assertEqual(plan.by_id["opt.start_page.company"].title, "Start page: my company (Shopware)")
        lead = support.run_fixture("lead-capture-flow.yaml").plan
        self.assertEqual(lead.by_id["opt.channel.landing_page"].title, "Channel: landing page")


class HygieneTest(GitRepoCase):
    def test_warnings_for_stale_doc_stray_worktree_and_ownership(self):
        self.build_stack()
        extra = os.path.join(self.tmp.name + "-preview")
        git(self.repo, "worktree", "add", "-q", "--detach", extra, "shop/theme")
        try:
            code, data = self.verify()
            self.assertEqual(code, 0, data)  # warnings never fail verify
            text = "\n".join(data["warnings"])
            self.assertIn("the plan document still shows 5 node(s) as planned", text)
            self.assertIn("extra worktree", text)
            self.assertIn("git worktree remove --force", text)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", extra], cwd=self.repo, capture_output=True)

    def test_brief_mentions_noop_ownership_and_commit_accuracy(self):
        from test_verify import cad
        out = cad("brief", self.doc, "dim.sync", cwd=self.repo).stdout
        self.assertIn("Also owns the no-op option(s) `none`", out)
        self.assertIn("Describe only changes that are in the commit.", out)


if __name__ == "__main__":
    unittest.main()
