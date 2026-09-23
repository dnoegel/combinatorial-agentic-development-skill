"""Thin, read-mostly helpers around the git command line."""

import subprocess

__all__ = ["GitError", "git", "is_repo", "toplevel", "has_remote", "branch_exists", "is_ancestor", "current_branch", "base_ref"]


class GitError(RuntimeError):
    pass


def git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def is_repo(path):
    return git(path, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip() == "true"


def toplevel(path):
    return git(path, "rev-parse", "--show-toplevel").stdout.strip()


def has_remote(repo, name="origin"):
    return name in git(repo, "remote", check=False).stdout.split()


def branch_exists(repo, branch):
    return git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def ref_exists(repo, ref):
    return git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def is_ancestor(repo, ancestor, descendant):
    return git(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode == 0


def current_branch(repo):
    return git(repo, "branch", "--show-current", check=False).stdout.strip()


def base_ref(repo, base_branch):
    """Where new root branches start: origin/<base> when that exists, else the local base."""
    remote = f"origin/{base_branch}"
    if repo and is_repo(repo) and has_remote(repo) and ref_exists(repo, remote):
        return remote
    return base_branch
