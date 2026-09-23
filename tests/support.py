import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "combinatorial-agentic-development", "scripts")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
CAD = os.path.join(SCRIPTS, "cad.py")

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from cadlib import engine, miniyaml, spec as spec_mod  # noqa: E402


def fixture(name):
    return os.path.join(FIXTURES, name)


def load_fixture(name):
    with open(fixture(name), encoding="utf-8") as fh:
        return miniyaml.loads(fh.read())


def spec_from(raw):
    return spec_mod.load(raw)


def run_fixture(name, **kwargs):
    return engine.run(spec_mod.load(load_fixture(name)), **kwargs)


def run_raw(raw, **kwargs):
    return engine.run(spec_mod.load(raw), **kwargs)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()
