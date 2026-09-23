"""End-to-end: planning document lifecycle, CLI, schemas and golden examples."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

import examples_builder
import support
from cadlib import document, miniyaml

SCHEMAS = os.path.join(support.ROOT, "skills", "combinatorial-agentic-development", "references")


def cad(*args, cwd=None):
    env = dict(os.environ, CAD_DATE="2026-09-23")
    return subprocess.run(
        [sys.executable, support.CAD, *args], capture_output=True, text=True, cwd=cwd, env=env, check=False
    )


def check_schema(value, schema, path="$"):
    """Minimal JSON Schema subset validator: type, const, enum, required,
    properties, additionalProperties, items, anyOf, minimum, minItems, pattern."""
    errors = []
    if "anyOf" in schema:
        if all(check_schema(value, s, path) for s in schema["anyOf"]):
            errors.append(f"{path}: matches no alternative")
        return errors
    types = schema.get("type")
    if types:
        types = types if isinstance(types, list) else [types]
        checks = {
            "object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "null": lambda v: v is None,
        }
        if not any(checks[t](value) for t in types):
            return [f"{path}: expected {types}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if "pattern" in schema and isinstance(value, str) and not re.search(schema["pattern"], value):
        errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if "minimum" in schema and isinstance(value, int) and value < schema["minimum"]:
        errors.append(f"{path}: below minimum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key!r}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                errors += check_schema(item, props[key], f"{path}.{key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors += check_schema(item, schema["additionalProperties"], f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: too few items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += check_schema(item, schema["items"], f"{path}[{i}]")
    return errors


def load_schema(name):  # noqa: D103
    with open(os.path.join(SCHEMAS, name), encoding="utf-8") as fh:
        return json.load(fh)


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.doc = os.path.join(self.tmp.name, "docs", "variants", "lead-capture-flow.md")
        os.environ["CAD_DATE"] = "2026-09-23"
        document.create(self.doc, "lead-capture-flow", spec_text=support.read(support.fixture("lead-capture-flow.yaml")))

    def tearDown(self):
        os.environ.pop("CAD_DATE", None)
        self.tmp.cleanup()

    def text(self):
        with open(self.doc, encoding="utf-8") as fh:
            return fh.read()

    def replace_spec(self, new_text):
        doc = document.read(self.doc)
        text = self.text().replace(doc.spec_text.rstrip("\n"), new_text.rstrip("\n"), 1)
        with open(self.doc, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_full_lifecycle(self):
        result, changed = document.render(self.doc)
        self.assertTrue(changed)
        text = self.text()
        self.assertEqual(text.count("```mermaid"), 2)
        self.assertIn("| Theoretical combinations (3 × 3 × 3 × 2) | 54 |", text)
        self.assertIn("| Removed by constraints | 12 |", text)
        self.assertIn("| **Valid product variants** | **42** |", text)
        self.assertIn("**Needs confirmation:**", text)
        self.assertIn("- **r1** (2026-09-23): Initial plan.", text)
        self.assertIn("<details><summary><b>1. Add lead capture flow foundation</b> <code>base</code></summary>", text)
        front = document.read(self.doc).front
        self.assertEqual(front["revision"], 1)
        self.assertNotIn("status", front)
        self.assertEqual(front["nodes"]["opt.pdf_delivery.email"], {
            "branch": "lead-capture-flow/pdf-delivery-email", "onto": "lead-capture-flow/pdf-delivery",
        })

        # Rendering again without spec changes keeps the revision.
        document.render(self.doc)
        self.assertEqual(document.read(self.doc).front["revision"], 1)

        # Update: a new conditional decision plus an interaction.
        self.replace_spec(support.read(support.fixture("lead-capture-flow-html-email.yaml")))
        document.render(self.doc, note="Emails can be HTML or plain text.", date="2026-09-24")
        self.assertEqual(document.read(self.doc).front["revision"], 2)
        text = self.text()
        self.assertIn("- **r2** (2026-09-24): Emails can be HTML or plain text.", text)
        self.assertRegex(text, r"Added: .*`dim.email_format`")
        self.assertIn("Valid variants 42 to 52", text)
        self.assertIn("| Collapsed, a decision does not apply | 36 |", text)

    def test_invalid_spec_leaves_document_untouched(self):
        document.render(self.doc)
        before = self.text()
        self.replace_spec("feature: lead-capture-flow\ndimensions:\n  a: [x]\nconstraints:\n  - never: a == x\n")
        broken = self.text()
        result, changed = document.render(self.doc)
        self.assertEqual(result.status, "error")
        self.assertFalse(changed)
        self.assertEqual(self.text(), broken)
        self.assertNotEqual(before, broken)

    def test_human_sections_survive_render(self):
        text = self.text().replace(
            "_What this feature is for and why these decisions are still open._", "Our own words."
        )
        with open(self.doc, "w", encoding="utf-8") as fh:
            fh.write(text)
        document.render(self.doc)
        document.render(self.doc)
        self.assertIn("Our own words.", self.text())
        self.assertEqual(self.text().count("<!-- cad:generated:end -->"), 1)


class CliTest(unittest.TestCase):
    def test_analyze_prints_receipt(self):
        proc = cad("analyze", support.fixture("lead-capture-flow.yaml"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertRegex(out, r"Theoretical combinations\s+54")
        self.assertRegex(out, r"Removed by constraints\s+12")
        self.assertRegex(out, r"Valid variants\s+42")
        self.assertIn("Status  needs confirmation", out)
        self.assertIn("Product decisions made on your behalf: 0", out)

    def test_analyze_json(self):
        for name in ("lead-capture-flow.yaml", "lead-capture-flow-html-email.yaml", "findings.yaml", "contradictory.yaml"):
            data = json.loads(cad("analyze", support.fixture(name), "--json").stdout)
            self.assertEqual(data["tool"], "combinatorial-agentic-development", name)
        data = json.loads(cad("analyze", support.fixture("lead-capture-flow.yaml"), "--json").stdout)
        self.assertEqual(data["counts"], {
            "theoretical": 54, "collapsed": 0, "invalid": 12, "valid": 42,
            "scenarios": 42, "configurable": 42, "nodes": 13,
        })
        self.assertEqual(len(data["nodes"][0]["mr_description"].splitlines()) > 3, True)

    def test_fixtures_match_spec_schema(self):
        schema = load_schema("spec.schema.json")
        for name in os.listdir(support.FIXTURES):
            with self.subTest(name=name):
                self.assertEqual(check_schema(support.load_fixture(name), schema), [])

    def test_errors_exit_non_zero_with_readable_message(self):
        proc = cad("analyze", support.fixture("contradictory.yaml"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("contradict", proc.stdout)
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write("feature: x\ndimensions:\n  a: [p, q]\nconstraints:\n  - if: a == r\n    requires: a == p\n")
        proc = cad("analyze", fh.name)
        os.unlink(fh.name)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unknown option 'r'", proc.stderr)

    def test_stack_dry_run_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "plan.md")
            self.assertEqual(cad("new", doc, "--spec", support.fixture("lead-capture-flow.yaml")).returncode, 0)
            self.assertEqual(cad("render", doc).returncode, 0)
            proc = cad("stack", doc)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("git switch -c lead-capture-flow/base origin/main", proc.stdout)
            self.assertNotIn("git push", proc.stdout)

    def test_new_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "plan.md")
            cad("new", doc, "--feature", "demo")
            proc = cad("new", doc, "--feature", "demo")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("already exists", proc.stderr)
            self.assertEqual(cad("render", doc).returncode, 0)


class GeneratedTextTest(unittest.TestCase):
    """Guard rails for everything the tool writes."""

    def test_outputs_have_no_em_dashes_or_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = examples_builder.build(tmp)
        for name, text in files.items():
            with self.subTest(name=name):
                self.assertNotIn(chr(0x2014), text)  # em dash
                self.assertNotRegex(text.lower(), r"generated by|co-authored|\bclaude\b|\bcodex\b|\bai assistant\b")


class ExamplesTest(unittest.TestCase):
    def test_examples_are_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = examples_builder.build(tmp)
        stale = []
        for name, text in files.items():
            path = os.path.join(support.ROOT, name)
            if not os.path.exists(path) or support.read(path) != text:
                stale.append(name)
        self.assertEqual(stale, [], "examples are stale: run python3 tests/examples_builder.py")


if __name__ == "__main__":
    unittest.main()
