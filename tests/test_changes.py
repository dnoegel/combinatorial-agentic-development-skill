"""Changes in the middle of a stack: cascades, amended parents, follow-ups, impact."""

import json
import os
import subprocess
import unittest

import support  # noqa: F401  (puts cadlib on the path)
from cadlib import document, miniyaml
from test_verify import GitRepoCase, cad, git


def show(repo, ref):
    return subprocess.run(["git", "show", ref], cwd=repo, capture_output=True, text=True).stdout


def sha(repo, ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=repo, capture_output=True, text=True).stdout.strip()


class CascadeTest(GitRepoCase):
    def test_change_on_base_cascades_through_the_whole_tree(self):
        self.build_stack()
        self.assertEqual(self.verify()[0], 0)  # records fork points
        git(self.repo, "switch", "-q", "shop/base")
        self.write("base-fix.txt", "fix\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "Fix base")
        git(self.repo, "switch", "-q", "main")

        proc = cad("restack", self.doc, cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        order = [line.split()[1].rstrip(":") for line in proc.stdout.splitlines() if line.startswith("# ") and ":" in line and "onto" in line]
        self.assertEqual(order, ["dim.theme", "dim.sync", "opt.theme.light", "opt.theme.dark"])

        proc = cad("restack", self.doc, "--execute", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Restacked 4 branch(es).", proc.stdout)
        for branch in ("shop/theme", "shop/sync", "shop/theme-light", "shop/theme-dark"):
            self.assertIn("fix", show(self.repo, f"{branch}:base-fix.txt"))
        self.assertIn("opts/theme-dark.txt", subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "shop/theme-dark"], cwd=self.repo, capture_output=True, text=True).stdout)
        code, data = self.verify("--integration", "--probe")
        self.assertEqual(code, 0, data)

    def test_amended_middle_node_replays_only_the_childs_commits(self):
        self.node_branch("shop/base", "main")
        self.node_branch("shop/theme", "shop/base", ["theme.txt"])
        self.node_branch("shop/theme-light", "shop/theme", ["opts/theme-light.txt"])
        git(self.repo, "switch", "-q", "main")
        self.verify()  # fork point of theme-light = current theme tip
        old_theme = sha(self.repo, "shop/theme")

        git(self.repo, "switch", "-q", "shop/theme")
        self.write("theme.txt", "rewritten\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--amend", "-m", "Add theme abstraction (reworked)")
        git(self.repo, "switch", "-q", "main")

        proc = cad("restack", self.doc, "--execute", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(old_theme[:12], proc.stdout)  # the recorded fork point, not the merge base
        self.assertEqual(show(self.repo, "shop/theme-light:theme.txt"), "rewritten\n")
        log = subprocess.run(["git", "log", "--format=%s", "shop/base..shop/theme-light"], cwd=self.repo,
                             capture_output=True, text=True).stdout.splitlines()
        self.assertEqual(log, ["Work on shop/theme-light", "Add theme abstraction (reworked)"])

    def test_nothing_to_restack(self):
        self.build_stack()
        proc = cad("restack", self.doc, cwd=self.repo)
        self.assertIn("Nothing to restack", proc.stdout)


class ContractChangeTest(GitRepoCase):
    def edit_spec(self, change):
        raw = miniyaml.loads(document.read(self.doc).spec_text)
        change(raw)
        doc = document.read(self.doc)
        with open(self.doc, encoding="utf-8") as fh:
            text = fh.read()
        with open(self.doc, "w", encoding="utf-8") as fh:
            fh.write(text.replace(doc.spec_text.rstrip("\n"), miniyaml.dumps(raw).rstrip("\n"), 1))

    def test_merged_node_gets_a_follow_up_instead_of_a_rewrite(self):
        self.node_branch("shop/base", "main")
        git(self.repo, "switch", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge base", "shop/base")
        document.render(self.doc)  # git shows base merged: its contract is snapshotted
        self.assertIn("base", document.read(self.doc).contracts)

        self.edit_spec(lambda raw: raw.setdefault("constraints", []).append({"never": "theme == dark and sync == crm"}))
        result, changed = document.render(self.doc, note="Dark theme cannot sync.")
        self.assertTrue(changed)
        front = document.read(self.doc).front
        self.assertEqual(front["followups"][0]["id"], "base.r2")
        self.assertIn("+ rule: never theme == dark and sync == crm", front["followups"][0]["changes"])
        node = result.plan.by_id["base.r2"]
        self.assertEqual(node.kind, "followup")
        # stacked on the merged base, so the dry run starts it from main
        self.assertIn("git switch -c shop/base-r2 main", cad("stack", self.doc, cwd=self.repo).stdout)
        # planned work that builds on base now builds on the revision
        self.assertIn("base.r2", result.plan.by_id["dim.theme"].depends_on)
        text = open(self.doc, encoding="utf-8").read()
        self.assertIn("Follow-up planned: `base.r2`, because `base` is merged and its contract changed.", text)
        self.assertIn("Revise shop foundation for plan revision 2", text)
        # a second render does not plan the same follow-up again
        document.render(self.doc)
        self.assertEqual(len(document.read(self.doc).front["followups"]), 1)

    def test_open_node_change_is_logged_once(self):
        self.build_stack()
        document.render(self.doc)
        self.edit_spec(lambda raw: raw["dimensions"]["theme"].append("blue"))
        document.render(self.doc, note="A blue theme.")
        text = open(self.doc, encoding="utf-8").read()
        self.assertIn("Changed after work started: `dim.theme` (+ decision: theme in [light, dark, blue]", text)
        self.assertNotIn("Changed after work started: `opt.theme.light`", text)
        document.render(self.doc)
        self.assertEqual(open(self.doc, encoding="utf-8").read().count("Changed after work started: `dim.theme`"), 1)


class LayoutChangeTest(GitRepoCase):
    edit_spec = ContractChangeTest.edit_spec

    def test_restack_is_reported_when_a_started_branch_needs_a_new_parent(self):
        self.build_stack()
        document.render(self.doc)  # records where each branch was built
        self.edit_spec(lambda raw: raw.setdefault("constraints", []).append(
            {"if": "theme == dark", "requires": "sync == crm"}))
        result, _ = document.render(self.doc, note="Dark theme needs the CRM.")
        text = open(self.doc, encoding="utf-8").read()
        self.assertIn("Restack needed: `opt.theme.dark` from `shop/theme`", text)
        self.assertNotEqual(result.stack.placements["opt.theme.dark"].parent, "dim.theme")

    def test_branches_for_removed_nodes_are_reported(self):
        self.build_stack()
        document.render(self.doc)
        self.edit_spec(lambda raw: raw["dimensions"].__setitem__("theme", ["light"]))
        document.render(self.doc, note="Only a light theme.")
        text = open(self.doc, encoding="utf-8").read()
        self.assertIn("Branches exist for nodes no longer planned: `opt.theme.dark`", text)


class ImpactTest(GitRepoCase):
    def test_impact_of_base_and_of_a_leaf(self):
        self.build_stack()
        data = json.loads(cad("impact", self.doc, "base", "--json", cwd=self.repo).stdout)
        self.assertEqual(data["status"], "branched")
        self.assertEqual(sorted(data["code_dependents"]), ["dim.sync", "dim.theme", "opt.theme.dark", "opt.theme.light"])
        self.assertEqual(len(data["scenarios"]), 4)
        leaf = json.loads(cad("impact", self.doc, "opt.theme.dark", "--json", cwd=self.repo).stdout)
        self.assertEqual((leaf["code_dependents"], leaf["stack_descendants"]), ([], []))
        self.assertEqual(leaf["scenarios"], ["T03", "T04"])
        text = cad("impact", self.doc, "dim.theme", cwd=self.repo).stdout
        self.assertIn("cad.py restack", text)
        self.assertIn("--only dim.theme", text)

    def test_probe_can_be_limited_to_affected_scenarios(self):
        self.build_stack(skip_files=("opts/theme-dark.txt",))
        code, data = self.verify("--integration", "--probe", "--only", "opt.theme.light")
        self.assertEqual(code, 0, data)
        self.assertEqual(data["probe"]["scenarios"], 2)
        code, data = self.verify("--integration", "--probe", "--only", "opt.theme.dark")
        self.assertEqual(code, 1)
        self.assertIn("(T03, T04)", data["issues"][0]["text"])


if __name__ == "__main__":
    unittest.main()
