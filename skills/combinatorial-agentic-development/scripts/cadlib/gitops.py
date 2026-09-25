"""Thin, read-mostly helpers around the git command line."""

import functools
import os
import subprocess

__all__ = [
    "GitError", "git", "is_repo", "toplevel", "has_remote", "branch_exists", "is_ancestor",
    "current_branch", "base_ref", "refs", "merged_into",
]


class GitError(RuntimeError):
    pass


def git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def is_repo(path):
    return toplevel_or_none(path) is not None


def toplevel(path):
    top = toplevel_or_none(path)
    if top is None:
        raise GitError(f"{path} is not inside a git repository")
    return top


@functools.lru_cache(maxsize=256)
def _toplevel_cached(path):
    proc = git(path, "rev-parse", "--show-toplevel", check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def toplevel_or_none(path):
    """Repository root for `path`, or None. Cached: repositories do not move during a run."""
    return _toplevel_cached(os.path.abspath(path))


def has_remote(repo, name="origin"):
    return name in git(repo, "remote", check=False).stdout.split()


def branch_exists(repo, branch):
    return git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def ref_exists(repo, ref):
    return git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def is_ancestor(repo, ancestor, descendant):
    if _is_sha(ancestor) and _is_sha(descendant):
        return _is_ancestor_sha(repo, ancestor, descendant)
    return git(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def _is_sha(text):
    return len(text) == 40 and all(c in "0123456789abcdef" for c in text)


@functools.lru_cache(maxsize=4096)
def _is_ancestor_sha(repo, ancestor, descendant):
    """Ancestry between two commits never changes, so it is safe to cache."""
    return git(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def current_branch(repo):
    return git(repo, "branch", "--show-current", check=False).stdout.strip()


def base_ref(repo, base_branch):
    """Where new root branches start: origin/<base> when that exists, else the local base."""
    remote = f"origin/{base_branch}"
    if repo and is_repo(repo) and has_remote(repo) and ref_exists(repo, remote):
        return remote
    return base_branch


def refs(repo, prefix="refs/heads/"):
    """All refs under `prefix` in one call: {short name: sha}."""
    out = git(repo, "for-each-ref", "--format=%(refname) %(objectname)", prefix, check=False).stdout
    result = {}
    for line in out.splitlines():
        name, _, sha = line.partition(" ")
        result[name[len(prefix):]] = sha
    return result


def merged_into(repo, base):
    """Local branches whose tip is contained in `base`, in one call."""
    out = git(repo, "branch", "--format=%(refname:short)", "--merged", base, check=False).stdout
    return set(out.split())
