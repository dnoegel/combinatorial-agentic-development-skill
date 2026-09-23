"""verify, brief, remote detection and the progress guard, against real git repositories."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

import support
from cadlib import document

SPEC = """\
feature: shop
dimensions:
  theme: [light, dark]
  sync:
    options: [crm, none]
    bundle: true
verify:
  test: python3 check.py
  probe: python3 probe.py
"""

# The "product": a file per implemented option. The probe observes an option
# only if its file exists, which is exactly how an unwired option shows up.
PROBE = """\
import json, os, sys
variant = json.loads(os.environ["CAD_VARIANT"])
seen = []
for dim, value in variant.items():
    if value is None:
        continue
    if value == "none" or os.path.exists(f"opts/{dim}-{value}.txt"):
        seen.append(f"{dim}={value}")
print(" ".join(seen))
"""


def cad(*args, cwd):
    return subprocess.run(
        [sys.executable, support.CAD, *args], capture_output=True, text=True, cwd=cwd,
        env=dict(os.environ, CAD_DATE="2026-09-23"), check=False,
    )


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class GitRepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        self.doc = os.path.join(self.repo, "docs", "variants", "shop.md")
        os.environ["CAD_DATE"] = "2026-09-23"
        document.create(self.doc, "shop", spec_text=SPEC)
        document.render(self.doc)
        document.approve(self.doc, "Dana")
        self.write("probe.py", PROBE)
        self.write("check.py", "print('ok')\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "Add plan")

    def tearDown(self):
        os.environ.pop("CAD_DATE", None)
        self.tmp.cleanup()

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def node_branch(self, branch, parent, files=()):
        git(self.repo, "switch", "-q", "-c", branch, parent)
        for name in files:
            self.write(name, name + "\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", f"Work on {branch}")

    def build_stack(self, skip_files=()):
        """base, dim.theme, opt.theme.light, opt.theme.dark, dim.sync (bundled with crm)."""
        self.node_branch("shop/base", "main")
        self.node_branch("shop/theme", "shop/base")
        self.node_branch("shop/sync", "shop/base", [f for f in ["opts/sync-crm.txt"] if f not in skip_files])
        self.node_branch("shop/theme-light", "shop/theme", [f for f in ["opts/theme-light.txt"] if f not in skip_files])
        self.node_branch("shop/theme-dark", "shop/theme", [f for f in ["opts/theme-dark.txt"] if f not in skip_files])
        git(self.repo, "switch", "-q", "main")

    def verify(self, *flags):
        proc = cad("verify", self.doc, "--json", *flags, cwd=self.repo)
        return proc.returncode, json.loads(proc.stdout)


class VerifyTest(GitRepoCase):
    def test_everything_green(self):
        self.build_stack()
        code, data = self.verify("--integration", "--probe")
        self.assertEqual(code, 0, data)
        self.assertTrue(all(s == "branched" for s in data["nodes"].values()))
        self.assertEqual(data["probe"], {"scenarios": 4, "failing": 0, "errors": 0})
        # verify never touches the checked-out branch or leaves worktrees behind
        self.assertEqual(subprocess.run(["git", "branch", "--show-current"], cwd=self.repo, capture_output=True, text=True).stdout.strip(), "main")
        worktrees = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertEqual(len(worktrees.strip().splitlines()), 1)

    def test_unwired_option_is_caught_by_the_probe(self):
        self.build_stack(skip_files=("opts/theme-dark.txt",))
        # Every branch exists and merges fine, which is what fooled us before.
        code, data = self.verify("--integration")
        self.assertEqual(code, 0)
        code, data = self.verify("--integration", "--probe")
        self.assertEqual(code, 1)
        issue = next(i for i in data["issues"] if i["check"] == "probe")
        self.assertEqual(issue["node"], "opt.theme.dark")
        self.assertIn("`theme=dark` is selected in 2 scenario(s) but the probe never observes it", issue["text"])

    def test_stale_branch_is_reported_with_a_fix(self):
        self.build_stack()
        git(self.repo, "switch", "-q", "shop/base")
        self.write("late.txt", "late\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "Late change on base")
        git(self.repo, "switch", "-q", "main")
        code, data = self.verify()
        self.assertEqual(code, 1)
        stale = sorted(i["node"] for i in data["issues"])
        self.assertEqual(stale, ["dim.sync", "dim.theme"])
        theme = next(i for i in data["issues"] if i["node"] == "dim.theme")
        self.assertIn("2 branch(es) built on it must follow: opt.theme.light, opt.theme.dark", theme["text"])
        self.assertEqual(theme["fix"], "cad.py restack <doc> dim.theme")

    def test_integration_conflict_is_reported(self):
        self.node_branch("shop/base", "main")
        self.node_branch("shop/theme", "shop/base")
        self.node_branch("shop/theme-light", "shop/theme")
        self.write("shared.txt", "light\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "light edits shared")
        self.node_branch("shop/theme-dark", "shop/theme")
        self.write("shared.txt", "dark\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "dark edits shared")
        git(self.repo, "switch", "-q", "main")
        code, data = self.verify("--integration")
        self.assertEqual(code, 1)
        issue = next(i for i in data["issues"] if i["check"] == "integration")
        self.assertEqual(issue["node"], "opt.theme.dark")
        self.assertIn("`shared.txt`", issue["text"])

    def test_failing_test_command_is_reported(self):
        self.build_stack()
        git(self.repo, "switch", "-q", "shop/theme-dark")
        self.write("check.py", "raise SystemExit('broken')\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "Break the checks")
        git(self.repo, "switch", "-q", "main")
        code, data = self.verify("--integration")
        self.assertEqual(code, 1)
        self.assertIn("`python3 check.py` fails with all branches merged", data["issues"][0]["text"])

    def test_text_output_mentions_skipped_checks(self):
        proc = cad("verify", self.doc, cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("5 planned", proc.stdout)
        self.assertIn("not run: --integration, --probe", proc.stdout)


class BriefAndStackTest(GitRepoCase):
    def test_brief_for_next_node(self):
        proc = cad("brief", self.doc, "--next", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# Brief: `base`", proc.stdout)
        self.assertIn("git switch -c shop/base main", proc.stdout)
        self.assertIn("`python3 check.py` passes on `shop/base`", proc.stdout)
        self.assertIn("If something in this brief cannot be done as written, stop and report it", proc.stdout)
        self.node_branch("shop/base", "main")
        git(self.repo, "switch", "-q", "main")
        proc = cad("brief", self.doc, "--next", cwd=self.repo)
        self.assertIn("# Brief: `dim.theme`", proc.stdout)
        self.assertIn("git switch -c shop/theme shop/base", proc.stdout)

    def test_brief_for_option_has_probe_and_commit_subject(self):
        proc = cad("brief", self.doc, "opt.theme.dark", cwd=self.repo)
        self.assertIn("The probe observes `theme=dark` in exactly the scenarios that select it", proc.stdout)
        self.assertIn("Subject: `Add dark theme`", proc.stdout)

    def test_stack_without_remote_uses_local_base(self):
        proc = cad("stack", self.doc, cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("git switch -c shop/base main", proc.stdout)
        self.assertNotIn("origin", proc.stdout.replace("No remote configured", ""))
        self.assertNotIn("git push", proc.stdout)

    def test_stack_reads_progress_from_git(self):
        self.node_branch("shop/base", "main")
        git(self.repo, "switch", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge base", "shop/base")
        proc = cad("stack", self.doc, cwd=self.repo)
        self.assertIn("[1/5] merged base", proc.stdout)
        self.assertIn("git switch -c shop/theme main", proc.stdout)

    def test_mark_refuses_on_feature_branch(self):
        self.node_branch("shop/base", "main")
        proc = cad("mark", self.doc, "base", "--status", "branched", cwd=self.repo)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Progress is recorded on `main` only", proc.stderr)
        git(self.repo, "switch", "-q", "main")
        proc = cad("mark", self.doc, "base", "--status", "branched", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class PlanFindingsTest(unittest.TestCase):
    def test_missing_probe_warns(self):
        result = support.run_fixture("lead-capture-flow.yaml")
        self.assertTrue(any("No `verify.probe` configured" in f.text for f in result.findings))

    def test_parallel_file_overlap_warns(self):
        raw = support.load_fixture("lead-capture-flow.yaml")
        raw["plan"] = {
            "opt.channel.website": {"files": ["src/site.ts", "src/web.ts"]},
            "opt.crm_sync.hubspot": {"files": ["src/site.ts"]},
            "dim.channel": {"files": ["src/web.ts"]},
        }
        result = support.run_raw(raw)
        texts = [f.text for f in result.findings if "parallel lanes" in f.text]
        self.assertEqual(len(texts), 1)
        self.assertIn("`opt.channel.website` and `opt.crm_sync.hubspot`", texts[0])
        self.assertIn("`src/site.ts`", texts[0])


if __name__ == "__main__":
    unittest.main()
