"""Compare the plan with reality: git state, integration, and observable behavior.

Three checks, cheapest first:

state        every branch that exists sits on its planned parent and contains
             the parent's current tip (a stale branch needs a restack).
integration  all existing branches merged in stack order into a temporary
             worktree; merge conflicts fail, then the spec's test command runs.
probe        for every targeted variant, the spec's probe command reports the
             options it can observe in the product; each active option must be
             observed. This catches options that exist on a branch but are
             never wired into the product.

Nothing here touches branches or the working tree. The only writes are metadata
refs under refs/cad/base/, which remember each branch's fork point so restacks
replay exactly the branch's own commits.
"""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

from . import gitops

__all__ = ["Issue", "Report", "run", "observed_tokens"]


@dataclass
class Issue:
    check: str  # state | integration | probe
    node: object
    text: str
    fix: str = ""


@dataclass
class Report:
    nodes: dict = field(default_factory=dict)  # node -> inferred status
    issues: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    probe: dict = field(default_factory=dict)  # summary numbers

    @property
    def ok(self):
        return not self.issues


def _effective_parent(stack, statuses, nid):
    p = stack.placements[nid]
    if p.parent is None or statuses.get(p.parent) == "merged":
        return stack.base_branch
    return p.parent_branch


FORK_REF = "refs/cad/base/"


def fork_ref(branch):
    return FORK_REF + branch


def record_fork(repo, branch, parent):
    """Remember which parent commit a branch is based on (metadata ref, never a branch)."""
    tip = gitops.git(repo, "rev-parse", parent).stdout.strip()
    gitops.git(repo, "update-ref", fork_ref(branch), tip, check=False)


def old_base(repo, branch, parent):
    """The commit a branch was built on: the recorded fork point, else the merge base."""
    ref = fork_ref(branch)
    if gitops.ref_exists(repo, ref) and gitops.is_ancestor(repo, ref, branch):
        return gitops.git(repo, "rev-parse", ref).stdout.strip()
    return gitops.git(repo, "merge-base", parent, branch).stdout.strip()


def subtree(stack, node_id):
    out = [node_id]
    for nid in stack.order:
        if stack.placements[nid].parent in out and nid not in out:
            out.append(nid)
    return out


def check_state(repo, stack, report):
    base = stack.base_branch
    if not gitops.branch_exists(repo, base):
        report.issues.append(Issue("state", None, f"base branch `{base}` does not exist"))
        return
    for nid in stack.order:
        p = stack.placements[nid]
        if not gitops.branch_exists(repo, p.branch):
            report.nodes[nid] = "planned"
            continue
        report.nodes[nid] = "merged" if gitops.is_ancestor(repo, p.branch, base) else "branched"
    stale = []
    for nid in stack.order:
        if report.nodes[nid] != "branched":
            continue
        p = stack.placements[nid]
        parent = _effective_parent(stack, report.nodes, nid)
        if not gitops.branch_exists(repo, parent):
            report.issues.append(Issue(
                "state", nid, f"`{p.branch}` exists but its parent `{parent}` does not",
                "create the parent first, or recreate this branch from the right parent",
            ))
            continue
        if not gitops.is_ancestor(repo, parent, p.branch):
            stale.append(nid)
        else:
            record_fork(repo, p.branch, parent)
    reported = set()
    for nid in stale:
        if nid in reported:
            continue
        tree = [n for n in subtree(stack, nid) if report.nodes.get(n) == "branched"]
        reported.update(tree)
        p = stack.placements[nid]
        parent = _effective_parent(stack, report.nodes, nid)
        followers = [n for n in tree if n != nid]
        report.issues.append(Issue(
            "state", nid,
            f"`{p.branch}` is stale: `{parent}` has commits it does not contain"
            + (f"; {len(followers)} branch(es) built on it must follow: {', '.join(followers)}" if followers else ""),
            f"cad.py restack <doc> {nid}",
        ))
    missing = [n for n in stack.order if report.nodes[n] == "planned"]
    if missing:
        report.notes.append(f"{len(missing)} node(s) have no branch yet: {', '.join(missing)}")


def _run(cmd, cwd, env=None, stdin=None, timeout=600):
    return subprocess.run(
        cmd, shell=True, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, timeout=timeout, check=False
    )


def _tail(text, lines=12):
    rows = [r for r in (text or "").strip().splitlines() if r.strip()]
    return "\n".join(rows[-lines:])


def check_integration(repo, stack, report, test_cmd, keep_worktree=False):
    """Merge every existing branch in stack order into a temporary worktree."""
    base = stack.base_branch
    tmp = tempfile.mkdtemp(prefix="cad-verify-")
    path = os.path.join(tmp, "worktree")
    gitops.git(repo, "worktree", "add", "--detach", path, base)
    try:
        merged = []
        for nid in stack.order:
            if report.nodes.get(nid) != "branched":
                continue
            branch = stack.placements[nid].branch
            proc = gitops.git(path, "merge", "--no-ff", "--no-edit", "-m", f"verify: merge {branch}", branch, check=False)
            if proc.returncode != 0:
                files = gitops.git(path, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
                gitops.git(path, "merge", "--abort", check=False)
                report.issues.append(Issue(
                    "integration", nid,
                    f"`{branch}` conflicts with the branches merged before it"
                    + (f" in {', '.join(f'`{f}`' for f in files)}" if files else ""),
                    "move shared code into a common ancestor node, or discover modules at runtime "
                    "so parallel branches never edit the same file",
                ))
                continue
            merged.append(branch)
        report.notes.append(f"integration: merged {len(merged)} branch(es) into a temporary worktree")
        if test_cmd:
            proc = _run(test_cmd, path)
            if proc.returncode != 0:
                report.issues.append(Issue(
                    "integration", None,
                    f"`{test_cmd}` fails with all branches merged:\n{_tail(proc.stdout + proc.stderr)}",
                ))
            else:
                report.notes.append(f"integration: `{test_cmd}` passes with all branches merged")
        return path
    finally:
        if not keep_worktree:
            gitops.git(repo, "worktree", "remove", "--force", path, check=False)
            shutil.rmtree(tmp, ignore_errors=True)


def observed_tokens(text):
    """Parse `dim=option` tokens from probe output (whitespace or comma separated)."""
    out = set()
    for raw in text.replace(",", " ").split():
        if "=" in raw:
            dim, _, value = raw.partition("=")
            out.add((dim.strip(), value.strip()))
    return out


def check_probe(cwd, spec, scenarios, dims, report, probe_cmd):
    failures = {}
    failing_variants = 0
    errors = 0
    for sid, variant in scenarios:
        payload = {d: v for d, v in zip(dims, variant)}
        expected = {(d, v) for d, v in payload.items() if v is not None}
        env = dict(os.environ, CAD_VARIANT=json.dumps(payload, sort_keys=True))
        proc = _run(probe_cmd, cwd, env=env, stdin=json.dumps(payload, sort_keys=True), timeout=120)
        if proc.returncode != 0:
            errors += 1
            if errors <= 3:
                report.issues.append(Issue(
                    "probe", None, f"probe failed for {sid} {payload}:\n{_tail(proc.stderr or proc.stdout, 6)}",
                ))
            failing_variants += 1
            continue
        seen = {t for t in observed_tokens(proc.stdout) if t[0] in payload}
        missing = expected - seen
        wrong = {t for t in seen if t not in expected}
        if missing or wrong:
            failing_variants += 1
        for d, v in missing:
            failures.setdefault(("missing", d, v), []).append(sid)
        for d, v in wrong:
            failures.setdefault(("unexpected", d, v), []).append(sid)
    for (kind, d, v), ids in sorted(failures.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        node = f"opt.{d}.{v}"
        if kind == "missing":
            text = f"`{d}={v}` is selected in {len(ids)} scenario(s) but the probe never observes it ({', '.join(ids[:5])}{' ...' if len(ids) > 5 else ''})"
            fix = "wire the option into the product (registration, discovery, composition root) and emit its marker"
        else:
            text = f"the probe observes `{d}={v}` in {len(ids)} scenario(s) that did not select it ({', '.join(ids[:5])}{' ...' if len(ids) > 5 else ''})"
            fix = "the option leaks into variants that did not choose it; check defaults and fallbacks"
        report.issues.append(Issue("probe", node, text, fix))
    report.probe = {"scenarios": len(scenarios), "failing": failing_variants, "errors": errors}
    if not failing_variants:
        report.notes.append(f"probe: all {len(scenarios)} scenarios show exactly their selected options")


def run(repo, result, integration=False, probe=False, only=None):
    spec, stack = result.spec, result.stack
    report = Report()
    check_state(repo, stack, report)
    scenarios = [(f"T{i:02d}", v) for i, v in enumerate(result.scenarios.variants, 1)]
    if only:
        from .plan import dependents
        ids = {only, *dependents(result.plan, only)}
        wanted = {sid for n in result.plan.nodes if n.id in ids for sid in n.scenarios}
        scenarios = [(sid, v) for sid, v in scenarios if sid in wanted]
        report.notes.append(f"probe limited to {len(scenarios)} scenario(s) affected by `{only}`")
    test_cmd = spec.verify.get("test")
    probe_cmd = spec.verify.get("probe")
    if probe and not probe_cmd:
        report.issues.append(Issue("probe", None, "no `verify.probe` command in the spec", "add one; see references/verification.md"))
        probe = False
    if integration:
        path = check_integration(repo, stack, report, test_cmd, keep_worktree=probe)
        if probe:
            try:
                check_probe(path, spec, scenarios, result.space.dims, report, probe_cmd)
            finally:
                gitops.git(repo, "worktree", "remove", "--force", path, check=False)
                shutil.rmtree(os.path.dirname(path), ignore_errors=True)
    elif probe:
        check_probe(repo, spec, scenarios, result.space.dims, report, probe_cmd)
    return report
