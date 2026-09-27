"""verify, brief, remote detection and the progress guard, against real git repositories."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import types
import unittest

import support  # noqa: F401  (puts cadlib on the path)
from cadlib import cli, document

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
    """Run the CLI in-process (fast); test_end_to_end covers the real entry point."""
    out, err = io.StringIO(), io.StringIO()
    old_cwd, old_date = os.getcwd(), os.environ.get("CAD_DATE")
    os.chdir(cwd)
    os.environ["CAD_DATE"] = "2026-09-23"
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
    finally:
        os.chdir(old_cwd)
        if old_date is None:
            os.environ.pop("CAD_DATE", None)
        else:
            os.environ["CAD_DATE"] = old_date
    return types.SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class GitRepoCase(unittest.TestCase):
    """A repository with the approved plan, probe and checks committed on main.

    Built once per class and copied for every test, because creating repos is
    the slowest part of these tests.
    """

    spec_text = SPEC

    @classmethod
    def setUpClass(cls):
        cls._template = tempfile.TemporaryDirectory()
        repo = os.path.join(cls._template.name, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        git(repo, "config", "commit.gpgsign", "false")
        doc = os.path.join(repo, "docs", "variants", "shop.md")
        os.environ["CAD_DATE"] = "2026-09-23"
        try:
            document.create(doc, "shop", spec_text=cls.spec_text)
            document.render(doc)
        finally:
            os.environ.pop("CAD_DATE", None)
        for name, text in (("probe.py", PROBE), ("check.py", "print('ok')\n")):
            with open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "Add plan")

    @classmethod
    def tearDownClass(cls):
        cls._template.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        shutil.copytree(os.path.join(self._template.name, "repo"), self.repo, symlinks=True)
        self.doc = os.path.join(self.repo, "docs", "variants", "shop.md")
        os.environ["CAD_DATE"] = "2026-09-23"

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
        self.assertIn("the probe observes `theme=dark` in exactly those", proc.stdout)
        self.assertIn("Part of the Shop plan (docs/variants/shop.md)", proc.stdout)
        self.assertIn("## MR description", proc.stdout)
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


class HygieneTest(GitRepoCase):
    def test_warning_for_stray_worktree(self):
        self.build_stack()
        extra = os.path.join(self.tmp.name + "-preview")
        git(self.repo, "worktree", "add", "-q", "--detach", extra, "shop/theme")
        try:
            code, data = self.verify()
            self.assertEqual(code, 0, data)  # warnings never fail verify
            text = "\n".join(data["warnings"])
            self.assertIn("extra worktree", text)
            self.assertIn("git worktree remove --force", text)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", extra], cwd=self.repo, capture_output=True)

    def test_brief_mentions_noop_ownership_and_commit_accuracy(self):
        out = cad("brief", self.doc, "dim.sync", cwd=self.repo).stdout
        self.assertIn("Also owns the no-op option(s) `none`", out)
        self.assertIn("Describe only changes that are in the commit.", out)


if __name__ == "__main__":
    unittest.main()
