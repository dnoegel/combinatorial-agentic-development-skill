"""Compose a variant as a branch you can check out.

A variant branch is derived, never edited: it is the base branch plus every
existing branch meant for the base branch, plus the open branches of the
options the variant selects. Toggles still need their configuration, which
the command prints. Recomposing replaces the branch.
"""

import re

from . import gitops
from .verify import Report, check_state, merge_branch, merge_shared, open_nodes_for, temp_worktree

__all__ = ["variant_branch", "compose"]


def variant_branch(result, variant):
    values = [v for v in variant if v is not None]
    slug = re.sub(r"[^a-z0-9-]+", "-", "-".join(values).lower().replace("_", "-")).strip("-")
    prefix = result.spec.stack["branch_prefix"]
    return f"{prefix}/variant/{slug}" if prefix else f"variant/{slug}"


def compose(repo, result, variant):
    """Create or replace the variant branch. Returns (branch, merged branches, problems)."""
    report = Report()
    check_state(repo, result.stack, report)
    problems = [i.text for i in report.issues if i.check == "state" and "does not exist" in i.text]
    needed = open_nodes_for(result, variant)
    missing = [n for n in needed if report.nodes.get(n) != "branched"]
    if missing:
        problems.append("open branches missing for this variant: " + ", ".join(missing))
    if problems:
        return None, [], problems
    name = variant_branch(result, variant)
    if gitops.current_branch(repo) == name:
        return None, [], [f"`{name}` is checked out; switch away before recomposing it"]
    with temp_worktree(repo, result.stack.base_branch) as path:
        merged = merge_shared(path, result, report.nodes, report)
        problems += [i.text for i in report.issues if i.check == "integration"]
        for nid in needed:
            branch = result.stack.placements[nid].branch
            files = merge_branch(path, branch)
            if files is not None:
                problems.append(f"`{branch}` conflicts" + (f" in {', '.join(files)}" if files else ""))
                break
            merged.append(branch)
        if problems:
            return None, merged, problems
        head = gitops.git(path, "rev-parse", "HEAD").stdout.strip()
    gitops.git(repo, "branch", "-f", name, head)
    return name, merged, []
