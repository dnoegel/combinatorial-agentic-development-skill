"""Builds the files in examples/ from the fixtures.

    python3 tests/examples_builder.py      # rewrite examples/
    python3 -m unittest discover tests     # fails if examples/ is stale
"""

import contextlib
import io
import os
import re
import shutil
import subprocess
import sys

import support
from cadlib import cli, document

INTENT = (
    "Visitors take a short self-assessment test and we turn them into leads. Nobody has decided yet "
    "where the flow lives, how the PDF report is delivered, when we ask for the email address, or "
    "whether leads go to HubSpot. Instead of waiting for a decision, we plan all of it."
)
REVIEW_NOTES = """\
- `crm_sync = hubspot` with `email_capture = disabled` creates HubSpot contacts without an email
  address. Is that useful, or should it be a constraint? (open question)
- `website` and `landing_page` probably share one flow and differ in layout. If so,
  `bundle: true` on `channel` saves two MRs."""
UPDATE_NOTE = "Emails can be HTML or plain text. Sending the PDF after capture needs glue code."


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(args))
    if code != 0:
        raise RuntimeError(f"cad.py {' '.join(args)} failed with {code}")
    return out.getvalue()


def _set_date(value):
    os.environ["CAD_DATE"] = value


def _git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _branch(name, parent, message):
    _git("switch", "-q", "-c", name, parent)
    _git("commit", "-q", "--allow-empty", "-m", message)
    _git("switch", "-q", "main")


def build(workdir):
    """Generate the examples inside `workdir`, return {relative path: content}.

    Revision 2 is rendered inside a throwaway git repository with some work
    already merged or in progress, because progress is read from git.
    """
    old_cwd, old_date = os.getcwd(), os.environ.get("CAD_DATE")
    os.makedirs(os.path.join(workdir, "examples"), exist_ok=True)
    os.chdir(workdir)
    try:
        r1 = "examples/lead-capture-flow.md"
        _set_date("2026-09-23")
        _cli("new", r1, "--spec", support.fixture("lead-capture-flow.yaml"), "--intent", INTENT)
        with open(r1, encoding="utf-8") as fh:
            text = fh.read()
        text = re.sub(r"(## Review notes\n\n)_.*?_\n", lambda m: m.group(1) + REVIEW_NOTES + "\n", text, flags=re.S)
        with open(r1, "w", encoding="utf-8") as fh:
            fh.write(text)
        _cli("render", r1, "--note", "Initial plan for the lead capture flow.")
        dry_run = _cli("stack", r1)

        repo = os.path.join(workdir, "repo")
        os.makedirs(os.path.join(repo, "examples"))
        shutil.copy(r1, os.path.join(repo, "examples", "lead-capture-flow-r2.md"))
        os.chdir(repo)
        doc = "examples/lead-capture-flow-r2.md"
        _git("init", "-q", "-b", "main")
        _git("config", "user.email", "example@example.com")
        _git("config", "user.name", "Example")
        _git("add", "-A")
        _git("commit", "-q", "-m", "Add lead capture plan")
        _branch("lead-capture-flow/base", "main", "Add lead capture flow foundation")
        _git("merge", "-q", "--no-ff", "-m", "Merge foundation", "lead-capture-flow/base")
        _branch("lead-capture-flow/email-capture", "main", "Add email capture abstraction")
        _git("merge", "-q", "--no-ff", "-m", "Merge email capture", "lead-capture-flow/email-capture")
        _branch("lead-capture-flow/email-capture-after-test", "main", "Capture the email after the test")
        _set_date("2026-09-25")
        _cli("render", doc)  # snapshot what the started nodes promised
        with open(support.fixture("lead-capture-flow-html-email.yaml"), encoding="utf-8") as fh:
            new_spec = fh.read().rstrip("\n")
        with open(doc, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace(document.read(doc).spec_text.rstrip("\n"), new_spec, 1)
        with open(doc, "w", encoding="utf-8") as fh:
            fh.write(text)
        _set_date("2026-09-28")
        _cli("render", doc, "--note", UPDATE_NOTE)
        dry_run_r2 = _cli("stack", doc)
        os.chdir(workdir)
        shutil.copy(os.path.join(repo, doc), "examples/lead-capture-flow-r2.md")

        with open("examples/lead-capture-flow.dry-run.txt", "w", encoding="utf-8") as fh:
            fh.write(dry_run)
        with open("examples/lead-capture-flow-r2.dry-run.txt", "w", encoding="utf-8") as fh:
            fh.write(dry_run_r2)
        out = {}
        for name in sorted(os.listdir("examples")):
            with open(os.path.join("examples", name), encoding="utf-8") as fh:
                out[f"examples/{name}"] = fh.read()
        return out
    finally:
        os.chdir(old_cwd)
        if old_date is None:
            os.environ.pop("CAD_DATE", None)
        else:
            os.environ["CAD_DATE"] = old_date


if __name__ == "__main__":
    import tempfile

    # Build outside any git repository so the dry runs never depend on local git state.
    with tempfile.TemporaryDirectory() as tmp:
        files = build(tmp)
    for name, text in files.items():
        with open(os.path.join(support.ROOT, name), "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {name}")
    sys.exit(0)
