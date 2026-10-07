"""Tests for skills/chronicle/scripts/chronicle.py (stdlib unittest, temp dirs, no network).

Run from the repo root:  python3 -m unittest discover -s tests -v
"""

import contextlib
import datetime
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "chronicle", "scripts", "chronicle.py")
_spec = importlib.util.spec_from_file_location("chronicle", SCRIPT)
chronicle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chronicle)

TODAY = datetime.date.today()
FINDING_RE = re.compile(r"^(ERROR|WARN) \S+: .+$")


def slashes(path):
    """Hook commands use forward slashes on Windows."""
    return path.replace("\\", "/") if os.name == "nt" else path


def memory_text(name, type_="decision", description=None, updated=None, body=None):
    description = description if description is not None else "Specific fact about %s" % name
    updated = updated or TODAY.isoformat()
    if body is None:
        body = "The fact about %s.\n\n**Why:** evidence.\n**How to apply:** do the thing." % name
    return "---\nname: %s\ndescription: %s\ntype: %s\nupdated: %s\n---\n%s\n" % (
        name, description, type_, updated, body)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="chronicle-test-")
        self.root = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.root, ".git"))
        self.mem = os.path.join(self.root, "docs", "memory")

    def tearDown(self):
        for dirpath, dirnames, filenames in os.walk(self.tmp):
            for name in dirnames + filenames:
                try:
                    os.chmod(os.path.join(dirpath, name), 0o755)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def write(self, rel, text, mode="w"):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if "b" in mode:
            with open(p, mode) as f:
                f.write(text)
        else:
            with open(p, mode, encoding="utf-8", newline="") as f:
                f.write(text)
        return p

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8", newline="") as f:
            return f.read()

    def add_memory(self, name, **kw):
        return self.write("docs/memory/%s.md" % name, memory_text(name, **kw))

    def reindex(self):
        chronicle.write_index(self.root)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = chronicle.main(list(argv))
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def run_cli(self, *argv, **kw):
        r = subprocess.run([sys.executable, SCRIPT] + list(argv), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, cwd=kw.get("cwd", self.root), timeout=kw.get("timeout"))
        return r.returncode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8")

    def lint(self):
        return chronicle.lint_store(self.root)[0]

    def assertFinding(self, findings, level, path_end, fragment):
        for lvl, path, msg in findings:
            if lvl == level and path.endswith(path_end) and fragment in msg:
                return
        self.fail("no %s for %s containing %r in:\n%s" % (
            level, path_end, fragment, "\n".join("%s %s: %s" % f for f in findings)))

    def assertNoFinding(self, findings, fragment):
        hits = [f for f in findings if fragment in f[2]]
        self.assertEqual(hits, [], "unexpected findings: %r" % hits)


# --------------------------------------------------------------------------- frontmatter


class FrontmatterTests(unittest.TestCase):
    parse = staticmethod(chronicle.parse_frontmatter)

    def test_basic(self):
        meta, body = self.parse("---\nname: abc\ntype: env\n---\nBody line\n")
        self.assertEqual(meta, {"name": "abc", "type": "env"})
        self.assertEqual(body, "Body line")

    def test_unquoted_colons_kept(self):
        meta, _ = self.parse("---\ndescription: Postgres: max 20 connections: per pod\n---\n")
        self.assertEqual(meta["description"], "Postgres: max 20 connections: per pod")

    def test_double_quotes_with_colon_and_escapes(self):
        meta, _ = self.parse('---\ndescription: "Auth: use \\"session\\" cookies, not C:\\\\tmp"\n---\n')
        self.assertEqual(meta["description"], 'Auth: use "session" cookies, not C:\\tmp')

    def test_single_quotes(self):
        meta, _ = self.parse("---\ndescription: 'It''s: fine # really'\n---\n")
        self.assertEqual(meta["description"], "It's: fine # really")

    def test_hash_is_not_a_comment(self):
        meta, _ = self.parse("---\ndescription: fixed in issue #12\n---\n")
        self.assertEqual(meta["description"], "fixed in issue #12")

    def test_crlf_bom_blank_and_comment_lines(self):
        meta, body = self.parse("\ufeff---\r\nname: abc\r\n\r\n# comment\r\ntype: env\r\n---\r\nB\r\n")
        self.assertEqual(meta, {"name": "abc", "type": "env"})
        self.assertEqual(body, "B")

    def test_errors(self):
        for text, fragment in (
            ("name: abc\n", "missing frontmatter"),
            ("", "missing frontmatter"),
            ("---\nname: abc\n", "not closed"),
            ("---\njust words\n---\n", "not `key: value`"),
            ("---\n  name: indented\n---\n", "not `key: value`"),
            ("---\nname: a\nname: b\n---\n", "duplicate key"),
        ):
            with self.assertRaises(chronicle.FrontmatterError) as cm:
                self.parse(text)
            self.assertIn(fragment, str(cm.exception))

    def test_yaml_scalar_round_trip(self):
        for value in ("plain words", "Auth: cookies", 'say "hi"', "- dash first", "issue #12 fixed",
                      "trailing colon:", "back\\slash: x", "'quoted'", "#hash first", "C# is fine"):
            rendered = chronicle.yaml_scalar(value)
            meta, _ = self.parse("---\ndescription: %s\n---\n" % rendered)
            self.assertEqual(meta["description"], value, rendered)
        self.assertEqual(chronicle.yaml_scalar("plain words"), "'plain words'")
        self.assertEqual(chronicle.yaml_scalar("Auth: cookies"), "'Auth: cookies'")

    def test_generated_values_always_single_quoted(self):
        """N6: plain YAML reads null/true/123/dates as non-strings; generated values never are plain."""
        for value in ("null", "true", "123", "2026-10-06", "~", "It's here", 'say "hi"', "back\\slash \\n"):
            rendered = chronicle.yaml_scalar(value)
            self.assertTrue(rendered.startswith("'") and rendered.endswith("'"), rendered)
            self.assertEqual(rendered[1:-1].replace("''", ""), value.replace("'", ""), "only ' is escaped")
            meta, _ = self.parse("---\ndescription: %s\n---\n" % rendered)
            self.assertEqual(meta["description"], value, rendered)
        meta, _ = self.parse("---\na: 'It''s'\nb: \"say \\\"hi\\\"\"\n---\n")
        self.assertEqual(meta, {"a": "It's", "b": 'say "hi"'}, "the parser reads both quote styles")

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML not installed")
    def test_generated_values_agree_with_yaml(self):
        import yaml

        for value in ("null", "true", "123", "2026-10-06", "It's: here # x", 'C:\\tmp "q"', "- dash"):
            rendered = chronicle.yaml_scalar(value)
            self.assertEqual(yaml.safe_load("description: %s\n" % rendered), {"description": value}, rendered)


# --------------------------------------------------------------------------- root resolution


class RootTests(RepoCase):
    def test_walks_up_to_git_dir(self):
        nested = self.path("a/b/c")
        os.makedirs(nested)
        self.assertEqual(chronicle.find_root(nested), self.root)

    def test_git_file_marks_worktree_root(self):
        wt = os.path.join(self.tmp, "worktree")
        os.makedirs(os.path.join(wt, "src"))
        with open(os.path.join(wt, ".git"), "w") as f:
            f.write("gitdir: %s/.git/worktrees/wt\n" % self.root)
        self.assertEqual(chronicle.find_root(os.path.join(wt, "src")), wt)

    def test_no_repo_returns_none(self):
        plain = tempfile.mkdtemp(prefix="chronicle-norepo-")
        try:
            d = os.path.abspath(plain)
            while True:  # never pass vacuously: skip loudly if the temp dir sits inside a repo
                if os.path.exists(os.path.join(d, ".git")):
                    self.skipTest("temp dir %s is inside a git repo (%s)" % (plain, d))
                if os.path.dirname(d) == d:
                    break
                d = os.path.dirname(d)
            self.assertIsNone(chronicle.find_root(plain))
            self.assertEqual(chronicle.repo_root(plain), os.path.abspath(plain))
        finally:
            shutil.rmtree(plain)


# --------------------------------------------------------------------------- index


class IndexTests(RepoCase):
    def make_store(self):
        self.add_memory("zeta-contract", type_="contract", description="Zeta contract")
        self.add_memory("alpha-decision", description="Alpha decision")
        self.add_memory("status-feat-billing", type_="status", description="Billing in flight")
        self.add_memory("beta-decision", description="Beta: decision")
        self.add_memory("ref-dashboard", type_="reference", description="Grafana board")
        self.add_memory("wsl-quirk", type_="env", description="WSL quirk")
        self.add_memory("enum-gotcha", type_="gotcha", description="Enum gotcha")

    def test_render_is_sectioned_sorted_and_deterministic(self):
        self.make_store()
        memories, _ = chronicle.scan_store(self.root)
        text = chronicle.render_index(list(reversed(memories)))
        self.assertEqual(text, chronicle.render_index(memories))
        expected = chronicle.INDEX_HEADER + (
            "\n## Status\n"
            "- [status-feat-billing](status-feat-billing.md) — Billing in flight\n"
            "\n## Decisions\n"
            "- [alpha-decision](alpha-decision.md) — Alpha decision\n"
            "- [beta-decision](beta-decision.md) — Beta: decision\n"
            "\n## Contracts\n"
            "- [zeta-contract](zeta-contract.md) — Zeta contract\n"
            "\n## Gotchas\n"
            "- [enum-gotcha](enum-gotcha.md) — Enum gotcha\n"
            "\n## Environment\n"
            "- [wsl-quirk](wsl-quirk.md) — WSL quirk\n"
            "\n## References\n"
            "- [ref-dashboard](ref-dashboard.md) — Grafana board\n"
        )
        self.assertEqual(text, expected)

    def test_header_matches_contract(self):
        header = chronicle.INDEX_HEADER
        self.assertTrue(header.startswith("# Project memory\n\n<!-- Generated by chronicle from "
                                          "docs/memory/*.md frontmatter; edit memory files, not this list.\n"))
        self.assertIn("To add a memory without the tool: create docs/memory/<slug>.md with the frontmatter "
                      "above, then add its line below in the right section (sorted by name).\n", header)
        self.assertTrue(header.endswith("Spec: https://github.com/jnopareboateng/chronicle -->\n"))

    def test_empty_sections_omitted_and_invalid_files_skipped(self):
        self.add_memory("only-decision")
        self.write("docs/memory/broken.md", "no frontmatter\n")
        self.add_memory("weird-type", type_="opinion")
        text = chronicle.render_index(chronicle.scan_store(self.root)[0])
        self.assertEqual(text.count("## "), 1)
        self.assertIn("## Decisions", text)
        self.assertNotIn("broken", text)
        self.assertNotIn("weird-type", text)

    def test_index_and_check_commands(self):
        self.make_store()
        rc, out, _ = self.run_main("index", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertIn("7 entries", out)
        self.assertEqual(self.run_main("index", "--check", "--cwd", self.root)[0], 0)
        self.add_memory("alpha-decision", description="Alpha decision, revised")
        before = self.read("docs/memory/MEMORY.md")
        rc, out, _ = self.run_main("index", "--check", "--cwd", self.root)
        self.assertEqual(rc, 1)
        self.assertIn("out of date", out)
        self.assertEqual(self.read("docs/memory/MEMORY.md"), before, "--check must not write")
        self.assertEqual(self.run_main("index", "--cwd", self.root)[0], 0)
        self.assertIn("Alpha decision, revised", self.read("docs/memory/MEMORY.md"))
        rc, out, _ = self.run_main("index", "--cwd", self.root)
        self.assertIn("unchanged", out)

    def test_check_accepts_crlf_checkout(self):
        self.make_store()
        self.reindex()
        text = self.read("docs/memory/MEMORY.md")
        self.write("docs/memory/MEMORY.md", text.replace("\n", "\r\n"))
        self.assertEqual(self.run_main("index", "--check", "--cwd", self.root)[0], 0)

    def test_index_without_store_fails(self):
        rc, _, err = self.run_main("index", "--cwd", self.root)
        self.assertEqual(rc, 2)
        self.assertIn("chronicle init", err)

    def test_unlistable_store_is_an_error_not_empty(self):
        """N5: a store that cannot be listed must never be indexed as empty."""
        self.make_store()
        self.reindex()
        before = self.read("docs/memory/MEMORY.md")
        real_listdir = os.listdir

        def listdir(path="."):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(self.mem)):
                raise PermissionError(13, "Permission denied", path)
            return real_listdir(path)

        with mock.patch.object(chronicle.os, "listdir", listdir):
            with self.assertRaises(chronicle.ChronicleError):
                chronicle.scan_store(self.root)
            for argv in (("index",), ("new", "decision", "late-fact", "-d", "Late"), ("init",), ("lint",)):
                rc, out, err = self.run_main(*(argv + ("--cwd", self.root)))
                self.assertEqual(rc, 2, argv)
                self.assertIn("cannot list docs/memory", err)
        self.assertEqual(self.read("docs/memory/MEMORY.md"), before, "index left unchanged")
        self.assertFalse(os.path.exists(self.path("docs/memory/late-fact.md")))
        self.assertEqual(chronicle.scan_store(os.path.join(self.tmp, "no-such-repo")), ([], []), "missing = empty")


# --------------------------------------------------------------------------- lint


class LintTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.add_memory("auth-cookie-sessions", description="Browser auth uses HttpOnly session cookies")
        self.add_memory("status-feat-billing", type_="status", description="Billing webhooks done, invoices next")
        self.reindex()

    def lint_after(self, rel, text, reindex=True, mode="w"):
        self.write(rel, text, mode)
        if reindex:
            self.reindex()
        return self.lint()

    def test_clean_store(self):
        self.assertEqual(self.lint(), [])
        rc, out, err = self.run_main("lint", "--cwd", self.root)
        self.assertEqual((rc, out), (0, ""))
        self.assertIn("2 memories, 0 errors, 0 warnings", err)

    def test_output_format_and_exit_code(self):
        self.write("docs/memory/broken-one.md", "no frontmatter\n")
        rc, out, _ = self.run_main("lint", "--cwd", self.root)
        self.assertEqual(rc, 1)
        lines = out.splitlines()
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, FINDING_RE)

    # errors

    def test_missing_frontmatter(self):
        f = self.lint_after("docs/memory/plain-notes.md", "# Notes\nsome text\n")
        self.assertFinding(f, "ERROR", "plain-notes.md", "missing frontmatter")

    def test_plain_document_reported_once(self):
        f = self.lint_after("docs/memory/PHASE_STATUS.md", "# Phase\nClaude did this session.\n" + "x" * 5000)
        own = [x for x in f if x[1].endswith("PHASE_STATUS.md")]
        self.assertEqual(len(own), 1, own)
        self.assertIn("not a memory file", own[0][2])
        f = self.lint_after("docs/memory/PHASE_STATUS.md", "# Phase\nkey ghp_" + "a" * 30 + "\n")
        self.assertFinding(f, "ERROR", "PHASE_STATUS.md", "possible secret")

    def test_bad_frontmatter_line(self):
        f = self.lint_after("docs/memory/bad-line.md", "---\nname: bad-line\nnot a pair\n---\nx\n")
        self.assertFinding(f, "ERROR", "bad-line.md", "bad frontmatter")

    def test_missing_field(self):
        f = self.lint_after("docs/memory/no-date.md", "---\nname: no-date\ndescription: d\ntype: env\n---\nx\n")
        self.assertFinding(f, "ERROR", "no-date.md", "missing frontmatter field(s): updated")

    def test_name_mismatch(self):
        f = self.lint_after("docs/memory/file-name.md", memory_text("other-name"))
        self.assertFinding(f, "ERROR", "file-name.md", "does not match filename")

    def test_invalid_name_and_filename(self):
        f = self.lint_after("docs/memory/Bad_Name.md", memory_text("Bad_Name"))
        self.assertFinding(f, "ERROR", "Bad_Name.md", "invalid name")
        self.assertFinding(f, "ERROR", "Bad_Name.md", "invalid filename")

    def test_invalid_type(self):
        f = self.lint_after("docs/memory/typo-type.md", memory_text("typo-type", type_="decisions"))
        self.assertFinding(f, "ERROR", "typo-type.md", "invalid type (9-char value not shown)")

    def test_field_values_never_echoed(self):
        """B6: a credential pasted into a frontmatter field is not copied into lint output."""
        cred = "hunter2" + "Q9x7Zr4LmT2wVb8N"  # matches no secret pattern: only the non-echo rule hides it
        gh = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123"
        for field in ("name", "type", "updated"):
            for value in (cred, gh):
                text = re.sub(r"^%s: .*$" % field, lambda _: "%s: %s" % (field, value), memory_text("leaky-field"),
                              count=1, flags=re.M)
                self.write("docs/memory/leaky-field.md", text)
                self.reindex()
                rc, out, err = self.run_main("lint", "--cwd", self.root)
                self.assertEqual(rc, 1, out)
                self.assertNotIn(value, out + err, "lint echoed the %s value" % field)
                self.assertIn("ERROR docs/memory/leaky-field.md: ", out)

    def test_link_and_duplicate_key_text_never_echoed(self):
        """Raw link targets and duplicate key names that do not look like slugs/fields stay out of output."""
        gh = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123"
        text = memory_text("leaky-link").rstrip("\n") + "\n\nRelated: [[%s]]\n" % gh
        self.write("docs/memory/leaky-link.md", text)
        self.reindex()
        rc, out, err = self.run_main("lint", "--cwd", self.root)
        self.assertNotIn(gh, out + err)
        self.assertIn("link not shown", out)
        dup = memory_text("leaky-key").replace("type: ", "%s: x\n%s: y\ntype: " % (gh, gh), 1)
        self.write("docs/memory/leaky-key.md", dup)
        rc, out, err = self.run_main("lint", "--cwd", self.root)
        self.assertNotIn(gh, out + err)

    def test_status_requires_prefix(self):
        f = self.lint_after("docs/memory/billing-work.md", memory_text("billing-work", type_="status"))
        self.assertFinding(f, "ERROR", "billing-work.md", "status-")

    def test_bad_dates(self):
        for value in ("06-10-2026", "2026-13-01", "Tuesday"):
            f = self.lint_after("docs/memory/dated.md", memory_text("dated", updated=value))
            self.assertFinding(f, "ERROR", "dated.md", "invalid updated date")

    def test_file_too_large(self):
        f = self.lint_after("docs/memory/huge.md", memory_text("huge", body="x" * 4100))
        self.assertFinding(f, "ERROR", "huge.md", "exceeds the 4000 byte limit")

    def test_index_out_of_date(self):
        f = self.lint_after("docs/memory/new-fact.md", memory_text("new-fact"), reindex=False)
        self.assertFinding(f, "ERROR", "MEMORY.md", "out of date")

    def test_index_missing(self):
        os.remove(self.path("docs/memory/MEMORY.md"))
        self.assertFinding(self.lint(), "ERROR", "MEMORY.md", "missing")

    def test_duplicate_index_lines(self):
        text = self.read("docs/memory/MEMORY.md")
        line = [l for l in text.splitlines() if l.startswith("- [auth")][0]
        f = self.lint_after("docs/memory/MEMORY.md", text + line + "\n", reindex=False)
        self.assertFinding(f, "ERROR", "MEMORY.md", "duplicate index lines for auth-cookie-sessions.md")
        self.assertFinding(f, "ERROR", "MEMORY.md", "out of date")

    def test_conflict_markers(self):
        body = "<<<<<<< HEAD\nfact one\n=======\nfact two\n>>>>>>> feat/x\n\n**Why:** w\n**How to apply:** h"
        f = self.lint_after("docs/memory/conflicted.md", memory_text("conflicted", body=body))
        self.assertFinding(f, "ERROR", "conflicted.md", "conflict marker at line 7")
        idx = self.read("docs/memory/MEMORY.md")
        f = self.lint_after("docs/memory/MEMORY.md", idx + "<<<<<<< ours\n=======\n>>>>>>> theirs\n", reindex=False)
        self.assertFinding(f, "ERROR", "MEMORY.md", "conflict marker")

    def test_setext_heading_is_not_a_conflict(self):
        body = "Retry policy\n=======\nThree retries, then fail.\n\n**Why:** w\n**How to apply:** h"
        f = self.lint_after("docs/memory/setext-heading.md", memory_text("setext-heading", body=body))
        self.assertNoFinding(f, "conflict marker")

    def test_last_updated_line(self):
        body = "**Last Updated:** Tuesday, 24-06-2026, 3:15 pm\nfact\n\n**Why:** w\n**How to apply:** h"
        f = self.lint_after("docs/memory/stamped.md", memory_text("stamped", body=body))
        self.assertFinding(f, "ERROR", "stamped.md", "`Last Updated:`")

    def test_secret_patterns(self):
        secrets = {
            "openai": "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2",
            "anthropic": "sk-ant-api03-" + "Abcdefghij0123456789xyz",
            "github": "ghp_" + "abcdefghijklmnopqrstuvwxyz0123",
            "github-pat": "github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnop",
            "slack": "xoxb-" + "123456789012-abcdefghijkl",
            "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
            "pem": "-----BEGIN RSA PRIVATE KEY-----",
        }
        for label, secret in secrets.items():
            name = "secret-%s" % label
            body = "Token is %s here.\n\n**Why:** w\n**How to apply:** h" % secret
            f = self.lint_after("docs/memory/%s.md" % name, memory_text(name, body=body))
            self.assertFinding(f, "ERROR", name + ".md", "possible secret")
            rc, out, _ = self.run_main("lint", "--cwd", self.root)
            self.assertNotIn(secret, out, "lint must not echo secrets")
            os.remove(self.path("docs/memory/%s.md" % name))
        self.reindex()
        self.assertNoFinding(self.lint(), "possible secret")

    def test_sk_inside_a_word_is_not_a_secret(self):
        body = "Queue task-abcdefghijklmnopqrstuvwxyz and disk-ABCDEFGHIJKLMNOPQRSTUVWX.\n\n**Why:** w\n**How to apply:** h"
        f = self.lint_after("docs/memory/task-ids.md", memory_text("task-ids", body=body))
        self.assertNoFinding(f, "possible secret")
        body = "Key (sk-abcdefghijklmnopqrstuvwx) leaked.\n\n**Why:** w\n**How to apply:** h"
        f = self.lint_after("docs/memory/task-ids.md", memory_text("task-ids", body=body))
        self.assertFinding(f, "ERROR", "task-ids.md", "possible secret (API key (sk-...))")

    def test_unfilled_template(self):
        rc, _, _ = self.run_main("new", "decision", "fresh-entry", "-d", "Fresh entry", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertFinding(self.lint(), "ERROR", "fresh-entry.md", "unfilled template placeholder")

    def test_invalid_utf8(self):
        f = self.lint_after("docs/memory/binary-junk.md", b"---\nname: \xff\xfe\n---\n", mode="wb")
        self.assertFinding(f, "ERROR", "binary-junk.md", "not valid UTF-8")

    def test_missing_store(self):
        shutil.rmtree(self.mem)
        f = self.lint()
        self.assertFinding(f, "ERROR", "docs/memory", "run chronicle init")

    # warnings

    def test_size_budget_warning(self):
        f = self.lint_after("docs/memory/wordy.md", memory_text("wordy", body="x" * 2100))
        self.assertFinding(f, "WARN", "wordy.md", "exceeds the 2000 byte budget")

    def test_long_description(self):
        f = self.lint_after("docs/memory/long-desc.md", memory_text("long-desc", description="d" * 101))
        self.assertFinding(f, "WARN", "long-desc.md", "description is 101 chars (budget 100)")
        f = self.lint_after("docs/memory/long-desc.md", memory_text("long-desc", description="d" * 100))
        self.assertNoFinding(f, "description is")

    def test_stale_status(self):
        old = (TODAY - datetime.timedelta(days=30)).isoformat()
        f = self.lint_after("docs/memory/status-old.md", memory_text("status-old", type_="status", updated=old))
        self.assertFinding(f, "WARN", "status-old.md", "not updated for 30 days")
        recent = (TODAY - datetime.timedelta(days=5)).isoformat()
        f = self.lint_after("docs/memory/status-old.md", memory_text("status-old", type_="status", updated=recent))
        self.assertNoFinding(f, "not updated for")

    def test_too_many_entries(self):
        for i in range(80):
            self.add_memory("bulk-%03d" % i, description="Bulk %d" % i)
        self.reindex()
        f = self.lint()
        self.assertFinding(f, "WARN", "MEMORY.md", "82 entries (budget 80)")
        self.assertNoFinding(f, "bytes (budget 9000)")

    def test_index_too_large(self):
        for i in range(55):
            self.add_memory("verbose-entry-number-%03d" % i, description=("Verbose %03d " % i) + "w" * 88)
        self.reindex()
        f = self.lint()
        self.assertGreater(len(self.read("docs/memory/MEMORY.md").encode("utf-8")), 9000)
        self.assertFinding(f, "WARN", "MEMORY.md", "bytes (budget 9000)")
        self.assertNoFinding(f, "entries (budget 80)")
        self.assertNoFinding(f, "description is")

    def test_legacy_files(self):
        self.write("docs/memory/UPDATE_LOG.md", "# Update Log\n## entry\n")
        self.write("docs/memory/updates/2026-01-01-x.md", "x\n")
        f = self.lint()
        self.assertFinding(f, "WARN", "docs/memory/UPDATE_LOG.md", "legacy memory")
        self.assertFinding(f, "WARN", "docs/memory/updates/", "legacy memory")
        self.assertNoFinding(f, "missing frontmatter")

    def test_non_memory_files(self):
        self.write("docs/memory/diagram.png", "png")
        os.makedirs(self.path("docs/memory/drafts"))
        f = self.lint()
        self.assertFinding(f, "WARN", "diagram.png", "not a memory file")
        self.assertFinding(f, "WARN", "drafts/", "not a memory file")

    def test_dotfiles_ignored(self):
        self.write("docs/memory/.gitkeep", "")
        self.write("docs/memory/.notes.md.swp", "x")
        self.assertEqual(self.lint(), [])
        self.assertEqual(self.run_main("lint", "--strict", "--cwd", self.root)[0], 0)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs os.mkfifo")
    def test_fifos_never_block(self):
        os.mkfifo(self.path("docs/memory/fifo-entry.md"))
        rc, out, _ = self.run_cli("index", timeout=10)
        self.assertEqual(rc, 0)
        rc, out, _ = self.run_cli("lint", timeout=10)
        self.assertIn("WARN docs/memory/fifo-entry.md: not a memory file", out)
        os.remove(self.path("docs/memory/MEMORY.md"))
        os.mkfifo(self.path("docs/memory/MEMORY.md"))
        rc, out, _ = self.run_cli("lint", timeout=10)
        self.assertEqual(rc, 1)
        self.assertIn("ERROR docs/memory/MEMORY.md: missing or unreadable", out)
        self.assertEqual(self.run_cli("context", timeout=10)[0], 0)

    def test_comment_markers_in_description(self):
        for name, desc in (("aaa-one", "Email templates must never contain <!-- comments"),
                           ("ccc-three", "Legacy --> arrows render in docs")):
            f = self.lint_after("docs/memory/%s.md" % name, memory_text(name, description=desc))
            self.assertFinding(f, "WARN", name + ".md", "`<!--` or `-->`")
        self.assertNoFinding(self.lint(), "out of date")

    def test_unquoted_yaml_unsafe_values(self):
        cases = (
            ("Billing branch: Stripe webhooks live", True),   # mapping value: YAML error
            ("fixed in issue #12", True),                      # ` #` starts a YAML comment
            ("`chronicle new` quotes values", True),           # reserved indicator
            ("- leading dash", True),
            ("ends with a colon:", True),
            ('"Billing branch: Stripe webhooks live"', False),
            ("'It''s: fine'", False),
            ("-x flag is required; see C:\\tmp and https://x.io/a", False),
            ("plain words, commas, 10:30 times", False),
        )
        for desc, unsafe in cases:
            f = self.lint_after("docs/memory/yaml-check.md", memory_text("yaml-check", description=desc))
            if unsafe:
                self.assertFinding(f, "WARN", "yaml-check.md", "unquoted `description` at line 3")
            else:
                self.assertNoFinding(f, "unquoted `")

    def test_personal_data(self):
        body = "Ask jane.doe@acme.io or call +233 24 123 4567.\n\n**Why:** w\n**How to apply:** h"
        f = self.lint_after("docs/memory/contact-info.md", memory_text("contact-info", body=body))
        self.assertFinding(f, "WARN", "contact-info.md", "email-like")
        self.assertFinding(f, "WARN", "contact-info.md", "phone-number-like")
        body = "Clone git@github.com:org/repo.git; released 2026-10-06; port 5432; v1.2.3.\n\n**Why:** w\n**How to apply:** h"
        f = self.lint_after("docs/memory/contact-info.md", memory_text("contact-info", body=body))
        self.assertNoFinding(f, "email-like")
        self.assertNoFinding(f, "phone-number-like")
        body = "US desk (555) 123-4567.\n\n**Why:** w\n**How to apply:** h"
        f = self.lint_after("docs/memory/contact-info.md", memory_text("contact-info", body=body))
        self.assertFinding(f, "WARN", "contact-info.md", "phone-number-like")

    def test_process_narration(self):
        for term in ("Claude", "Codex", "Opus", "Sonnet", "Haiku", "GPT-5", "subagent", "this session"):
            body = "Fixed by %s after review.\n\n**Why:** w\n**How to apply:** h" % term
            f = self.lint_after("docs/memory/narrated.md", memory_text("narrated", body=body))
            self.assertFinding(f, "WARN", "narrated.md", "process narration term `%s`" % term)

    def test_duplicate_description(self):
        f = self.lint_after("docs/memory/auth-copy.md",
                            memory_text("auth-copy", description="Browser auth uses HttpOnly session cookies"))
        self.assertFinding(f, "WARN", "auth-copy.md", "same description as")

    def test_empty_body_and_broken_link(self):
        f = self.lint_after("docs/memory/empty-body.md", memory_text("empty-body", body=""))
        self.assertFinding(f, "WARN", "empty-body.md", "empty body")
        body = "Fact.\n\n**Why:** w\n**How to apply:** h\n\nRelated: [[auth-cookie-sessions]] [[gone-entry]]"
        f = self.lint_after("docs/memory/linked.md", memory_text("linked", body=body))
        self.assertFinding(f, "WARN", "linked.md", "[[gone-entry]]")
        self.assertNoFinding(f, "[[auth-cookie-sessions]]")

    def test_strict_fails_on_warnings(self):
        self.lint_after("docs/memory/long-desc.md", memory_text("long-desc", description="d" * 150))
        self.assertEqual(self.run_main("lint", "--cwd", self.root)[0], 0)
        self.assertEqual(self.run_main("lint", "--strict", "--cwd", self.root)[0], 1)


# --------------------------------------------------------------------------- context


class ContextTests(RepoCase):
    def context(self, *extra, **kw):
        return self.run_cli("context", *extra, **kw)

    def test_v2_store(self):
        self.add_memory("auth-cookie-sessions", description="Browser auth uses cookies")
        self.add_memory("status-feat-x", type_="status", description="Feature x in flight")
        self.reindex()
        rc, out, err = self.context()
        self.assertEqual((rc, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0], chronicle.CONTEXT_HEADER)
        self.assertIn("- [auth-cookie-sessions](auth-cookie-sessions.md) — Browser auth uses cookies", lines)
        self.assertIn("## Status", lines)
        self.assertNotIn("<!--", out)
        self.assertNotIn("Generated by chronicle", out)
        self.assertNotIn("# Project memory", lines)

    def test_comment_markers_in_descriptions_survive(self):
        self.add_memory("aaa-one", description="Email templates must never contain <!-- comments")
        self.add_memory("bbb-two", description="Second entry stays visible")
        self.add_memory("ccc-three", description="Legacy --> arrows render in docs")
        self.reindex()
        rc, out, err = self.context()
        self.assertEqual((rc, err), (0, ""))
        lines = out.splitlines()
        for line in ("- [aaa-one](aaa-one.md) — Email templates must never contain <!-- comments",
                     "- [bbb-two](bbb-two.md) — Second entry stays visible",
                     "- [ccc-three](ccc-three.md) — Legacy --> arrows render in docs"):
            self.assertIn(line, lines)
        self.assertNotIn("Generated by chronicle", out)

    def test_only_the_header_comment_is_stripped(self):
        strip = chronicle.strip_header_comment
        for text in ("# T\n<!-- a -->\n<!-- b -->\n## S\n- x <!-- c -->\n",  # not the generated comment
                     "# T\n<!-- unclosed\n## S\n- y -->\n"):
            self.assertEqual(strip(text), text)
        self.assertEqual(strip(chronicle.INDEX_HEADER), "# Project memory\n\n\n")
        self.assertEqual(strip(chronicle.INDEX_HEADER + "<!-- mine -->\n"), "# Project memory\n\n\n<!-- mine -->\n")

    def test_sectionless_index_never_loses_entries(self):
        """B7b: comment markers in descriptions of an index without sections must not hide entries."""
        strip = chronicle.strip_header_comment
        entries = ("- [aaa-one](aaa-one.md) — opens <!-- here\n- [bbb-two](bbb-two.md) — middle entry\n"
                   "- [ccc-three](ccc-three.md) — closes --> here\n")
        self.assertEqual(strip("# Project memory\n\n" + entries), "# Project memory\n\n" + entries)
        self.assertEqual(strip(chronicle.INDEX_HEADER + entries), "# Project memory\n\n\n" + entries)
        unclosed = "# Project memory\n\n<!-- Generated by chronicle, hand-edited and never closed\n" + entries
        self.assertEqual(strip(unclosed), unclosed, "a generated comment never spans entry lines")
        self.write("docs/memory/MEMORY.md", "# Project memory\n\n" + entries)
        out = chronicle.context_text(self.root)
        for name in ("aaa-one", "bbb-two", "ccc-three"):
            self.assertIn("- [%s](%s.md)" % (name, name), out)

    def test_index_over_read_limit_is_reported(self):
        """B7a: entries past the read limit are never dropped silently."""
        self.add_memory("aaa-first", description="A" * 100)
        self.add_memory("zzz-later", description="Later entry")
        self.reindex()
        size = len(self.read("docs/memory/MEMORY.md").encode("utf-8"))
        limit = size - len("- [zzz-later](zzz-later.md) — Later entry\n".encode("utf-8"))  # read ends before it
        with mock.patch.object(chronicle, "INDEX_READ_MAX", limit):
            out = chronicle.context_text(self.root)
            self.assertIn("(docs/memory/MEMORY.md is over %d bytes: entries past that point are not shown; "
                          "run chronicle lint)" % limit, out.splitlines())
            self.assertIn("aaa-first", out)
            self.assertNotIn("zzz-later", out)
            self.assertFinding(self.lint(), "ERROR", "MEMORY.md", "exceeds the %d byte read limit" % limit)
        with mock.patch.object(chronicle, "INDEX_READ_MAX", size):
            out = chronicle.context_text(self.root)
            self.assertIn("zzz-later", out)
            self.assertNotIn("not shown", out)
            self.assertNoFinding(self.lint(), "read limit")

    def shown_names(self, out):
        """Entry names in context output, in order: full lines, then names-only lines."""
        names, compact = [], False
        for line in out.splitlines():
            m = chronicle.ENTRY_LINE_RE.match(line)
            if m:
                names.append(m.group(1)[:-3])
            elif line.startswith("## "):
                compact = line.endswith(" (names only; open docs/memory/<name>.md):")
            elif compact and not line.startswith("..."):
                self.assertLessEqual(len(line), chronicle.COMPACT_WIDTH, line)
                names.extend(n.strip() for n in line.split(",") if n.strip())
        return names

    def index_names(self):
        lines = self.read("docs/memory/MEMORY.md").splitlines()
        return [m.group(1)[:-3] for m in map(chronicle.ENTRY_LINE_RE.match, lines) if m]

    def assertAccounted(self, out, cap, complete=None):
        """Within cap; names in index order; any missing tail is counted on the last line."""
        self.assertLessEqual(len(out.encode("utf-8")), cap)
        expected, shown = self.index_names(), self.shown_names(out)
        self.assertEqual(shown, expected[:len(shown)], "every shown name, in index order, no repeats")
        if len(shown) < len(expected):
            self.assertEqual(out.splitlines()[-1], "... %d more in docs/memory/MEMORY.md" % (len(expected) - len(shown)))
        if complete is not None:
            self.assertEqual(len(shown) == len(expected), complete)
        return shown

    def make_realistic_store(self, n):
        """n entries spread over all six sections, 100-char descriptions (the pilot's shape)."""
        for i in range(n):
            type_ = chronicle.TYPES[i % len(chronicle.TYPES)]
            name = "%s%s-entry-%03d-quirk" % ("status-" if type_ == "status" else "", type_, i)
            desc = ("Entry %03d is a specific %s fact that agents must recall before touching this code" % (i, type_)
                    + " area" * 10)[:chronicle.DESCRIPTION_MAX]
            self.add_memory(name, type_=type_, description=desc)
        self.reindex()

    def test_max_bytes_has_a_floor(self):
        for i in range(30):
            self.add_memory("entry-%03d" % i, description="Description number %d with some words" % i)
        self.reindex()
        for value in ("0", "-5", "50"):
            rc, out, _ = self.context("--max-bytes", value)
            self.assertEqual(rc, 0)
            self.assertIn("entry-000", out)
            self.assertAccounted(out, chronicle.CONTEXT_MIN_BYTES)
        rc, out, _ = self.run_main("context", "--max-bytes", "0", "--cwd", self.root)
        self.assertAccounted(out, chronicle.CONTEXT_MIN_BYTES)
        self.assertIn("entry-000", out)

    def test_empty_store(self):
        self.run_main("init", "--cwd", self.root)
        rc, out, _ = self.context()
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), [chronicle.CONTEXT_HEADER, "(no entries yet)"])

    def test_legacy_store(self):
        self.write("docs/memory/UPDATE_LOG.md", "# Update Log\n" + "## entry\n" * 50)
        self.write("docs/memory/PROJECT_MEMORY.md", "# Project Memory\n## Section\n")
        self.write("docs/memory/updates/a.md", "a\n")
        rc, out, err = self.context()
        self.assertEqual((rc, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("docs/memory/UPDATE_LOG.md", lines[0])
        self.assertIn("docs/memory/PROJECT_MEMORY.md", lines[0])
        self.assertIn("docs/memory/updates/ (1 files)", lines[0])
        self.assertIn("Do NOT bulk-read UPDATE_LOG.md or updates/", lines[1])
        self.assertIn("section headings of PROJECT_MEMORY.md", lines[1])
        self.assertIn("chronicle skill", lines[1])

    def test_v2_and_legacy_mentions_leftovers(self):
        self.add_memory("one-fact")
        self.reindex()
        self.write("memory/PROJECT_MEMORY.md", "# old\n")
        rc, out, _ = self.context()
        self.assertEqual(rc, 0)
        self.assertIn("Legacy memory files still present (memory/PROJECT_MEMORY.md)", out.splitlines()[1])

    def test_empty_repo_prints_nothing(self):
        rc, out, err = self.context()
        self.assertEqual((rc, out, err), (0, "", ""))

    def test_every_name_reaches_agents_60_entries(self):
        """A real 60-entry pilot shape: 60 entries overflow 9000 bytes; the tail sections arrive by name."""
        self.make_realistic_store(60)
        self.assertGreater(len(self.read("docs/memory/MEMORY.md").encode("utf-8")), chronicle.CONTEXT_MAX_BYTES)
        rc, out, err = self.context()
        self.assertEqual((rc, err), (0, ""))
        self.assertAccounted(out, chronicle.CONTEXT_MAX_BYTES, complete=True)
        lines = out.splitlines()
        self.assertTrue(lines[2].startswith("- [status-"), "full lines first")
        self.assertIn("## References (names only; open docs/memory/<name>.md):", lines)
        self.assertNotIn("more in docs/memory/MEMORY.md", out)
        full = sum(1 for l in lines if l.startswith("- ["))
        self.assertGreater(full, 40, "full lines fill the budget before names-only starts")

    def test_every_name_reaches_agents_150_entries(self):
        self.make_realistic_store(150)
        rc, out, err = self.context()
        self.assertEqual((rc, err), (0, ""))
        shown = self.assertAccounted(out, chronicle.CONTEXT_MAX_BYTES, complete=True)
        self.assertEqual(len(shown), 150)
        for title in ("Gotchas", "Environment", "References"):
            self.assertIn("## %s (names only; open docs/memory/<name>.md):" % title, out.splitlines())
        self.assertGreater(len(out.encode("utf-8")), chronicle.CONTEXT_MAX_BYTES - 200, "budget used, not wasted")

    def test_budget_sweep_never_overflows_or_loses_a_name(self):
        self.make_realistic_store(150)
        self.write("docs/memory/UPDATE_LOG.md", "# legacy\n")  # a legacy line in the head too
        for cap in range(500, 26000, 157):
            out = chronicle.context_text(self.root, cap)
            self.assertAccounted(out, cap)
        self.assertAccounted(chronicle.context_text(self.root, 30000), 30000, complete=True)

    def test_names_overflow_ends_with_count(self):
        self.make_realistic_store(150)
        rc, out, _ = self.context("--max-bytes", "1200")
        shown = self.assertAccounted(out, 1200, complete=False)
        self.assertGreater(len(shown), 10)
        self.assertNotIn("- [", out, "names only: every byte goes to names")
        self.assertRegex(out.splitlines()[-1], r"^\.\.\. \d+ more in docs/memory/MEMORY\.md$")

    def test_non_entry_lines_dropped_with_a_note(self):
        self.make_realistic_store(30)
        text = self.read("docs/memory/MEMORY.md") + "".join("stray line %d from a bad merge\n" % i for i in range(40))
        self.write("docs/memory/MEMORY.md", text)
        out = chronicle.context_text(self.root, 3000)
        self.assertAccounted(out, 3000, complete=True)
        self.assertEqual(out.splitlines()[-1], "... (more lines in docs/memory/MEMORY.md)")
        self.write("docs/memory/MEMORY.md", "# Project memory\n" + "".join("prose %d\n" % i for i in range(2000)))
        out = chronicle.context_text(self.root, 2000)
        self.assertLessEqual(len(out.encode("utf-8")), 2000)
        self.assertEqual(out.splitlines()[-1], "... (more lines in docs/memory/MEMORY.md)")

    def test_compact_wrapping_keeps_planned_size(self):
        names = ["name-%03d-%s" % (i, "x" * (i % 40)) for i in range(120)]
        lines = chronicle._compact([("Decisions", names)])
        self.assertEqual(lines[0], "## Decisions (names only; open docs/memory/<name>.md):")
        self.assertGreater(len(lines), 3)
        self.assertEqual(", ".join(names), " ".join(lines[1:]))
        planned = chronicle._nbytes(lines[0]) + sum(len(n) for n in names) + 2 * (len(names) - 1) + 1
        self.assertEqual(sum(chronicle._nbytes(l) for l in lines), planned)

    def test_worktree_git_file_and_subdir(self):
        wt = os.path.join(self.tmp, "wt")
        os.makedirs(os.path.join(wt, "docs", "memory"))
        os.makedirs(os.path.join(wt, "src", "deep"))
        with open(os.path.join(wt, ".git"), "w") as f:
            f.write("gitdir: %s/.git/worktrees/wt\n" % self.root)
        with open(os.path.join(wt, "docs", "memory", "wt-fact.md"), "w") as f:
            f.write(memory_text("wt-fact", description="Worktree fact"))
        chronicle.write_index(wt)
        rc, out, _ = self.context(cwd=os.path.join(wt, "src", "deep"))
        self.assertEqual(rc, 0)
        self.assertIn("Worktree fact", out)
        rc, out, _ = self.context("--cwd", os.path.join(wt, "src"))
        self.assertIn("Worktree fact", out)

    def test_garbage_never_raises(self):
        os.makedirs(self.mem)
        cases = (
            b"\x00\x01\x02 binary junk \xff",
            b"\xff\xfe invalid utf-8 \xc3\x28 <!-- unclosed",
            b"",
        )
        for data in cases:
            self.write("docs/memory/MEMORY.md", data, mode="wb")
            rc, out, err = self.context()
            self.assertEqual((rc, err), (0, ""), data)
        os.remove(self.path("docs/memory/MEMORY.md"))
        os.makedirs(self.path("docs/memory/MEMORY.md"))
        rc, out, err = self.context()
        self.assertEqual((rc, err), (0, ""))

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs POSIX non-root")
    def test_unreadable_index(self):
        self.add_memory("one-fact")
        self.reindex()
        os.chmod(self.path("docs/memory/MEMORY.md"), 0)
        rc, out, err = self.context()
        self.assertEqual((rc, out, err), (0, "", ""))

    def test_bad_arguments_and_paths(self):
        for args in (["--max-bytes", "lots"], ["--bogus"], ["--cwd", os.path.join(self.tmp, "nope")],
                     ["--max-bytes"], ["--cwd"]):
            rc, out, err = self.context(*args)
            self.assertEqual((rc, err), (0, ""), args)

    def test_in_process_main_never_raises(self):
        os.makedirs(self.path("docs/memory/MEMORY.md"))
        rc, out, err = self.run_main("context", "--cwd", self.root)
        self.assertEqual(rc, 0)

    def test_fast_on_100_files(self):
        for i in range(100):
            self.add_memory("perf-entry-%03d" % i, description="Perf description %d" % i)
        self.reindex()
        self.write("docs/memory/UPDATE_LOG.md", "## x\n" * 20000)
        local_script = os.path.join(self.tmp, "chronicle.py")  # time the script, not a network share
        shutil.copy(SCRIPT, local_script)
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            r = subprocess.run([sys.executable, local_script, "context"], cwd=self.root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            timings.append(time.perf_counter() - start)
            self.assertEqual(r.returncode, 0)
            self.assertIn(b"perf-entry-099", r.stdout)
        median = sorted(timings)[2]
        sys.stderr.write("\n  context median wall time on 100 files: %.0f ms\n" % (median * 1000))
        # The 200 ms target is for Linux/WSL. On Windows, interpreter startup alone takes 150-300 ms.
        self.assertLess(median, 0.2 if os.name != "nt" else 0.6)


# --------------------------------------------------------------------------- new / init


class NewTests(RepoCase):
    def test_scaffold(self):
        rc, out, err = self.run_main("new", "decision", "auth-cookie-sessions", "--description",
                                     'Auth: "session" cookies,\n  not JWT', "--cwd", self.root)
        self.assertEqual(rc, 0, err)
        path = out.strip()
        self.assertEqual(os.path.realpath(path), os.path.realpath(self.path("docs/memory/auth-cookie-sessions.md")))
        meta, body = chronicle.parse_frontmatter(self.read("docs/memory/auth-cookie-sessions.md"))
        self.assertEqual(meta, {"name": "auth-cookie-sessions", "description": 'Auth: "session" cookies, not JWT',
                                "type": "decision", "updated": TODAY.isoformat()})
        self.assertIn("**Why:**", body)
        self.assertIn("**How to apply:**", body)
        index = self.read("docs/memory/MEMORY.md")
        self.assertIn('- [auth-cookie-sessions](auth-cookie-sessions.md) — Auth: "session" cookies, not JWT', index)
        self.assertEqual(self.read(".gitattributes").count(chronicle.UNION_LINE), 1)

    def test_filled_scaffold_lints_clean(self):
        self.run_main("new", "gotcha", "enum-autogen-drift", "-d", "Alembic misses enum values", "--cwd", self.root)
        p = "docs/memory/enum-autogen-drift.md"
        text = self.read(p).replace("<The fact first, 1-6 lines.>", "Autogenerate skips enum values.")
        text = text.replace("<reason, incident, or evidence>", "deploy failed").replace("<what to do / avoid>", "hand-write")
        self.write(p, text)
        self.assertEqual(self.lint(), [])

    def test_long_description_warns(self):
        rc, _, err = self.run_main("new", "decision", "wordy-fact", "-d", "d" * 101, "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertIn("description is 101 chars (budget 100)", err)
        rc, _, err = self.run_main("new", "decision", "tight-fact", "-d", "d" * 100, "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertNotIn("description is", err)

    def test_refuses_overwrite(self):
        self.run_main("new", "env", "wsl-path-quirk", "-d", "First", "--cwd", self.root)
        before = self.read("docs/memory/wsl-path-quirk.md")
        rc, _, err = self.run_main("new", "env", "wsl-path-quirk", "-d", "Second", "--cwd", self.root)
        self.assertEqual(rc, 2)
        self.assertIn("already exists", err)
        self.assertEqual(self.read("docs/memory/wsl-path-quirk.md"), before)

    def test_rejects_bad_input(self):
        for argv in (["decision", "Bad_Slug"], ["decision", "ab"], ["status", "feat-x"], ["decision", "ok-slug", "-d", "  "]):
            if "-d" not in argv:
                argv = argv + ["-d", "desc"]
            rc, _, _ = self.run_main("new", *(argv + ["--cwd", self.root]))
            self.assertEqual(rc, 2, argv)
        rc, _, _ = self.run_main("new", "opinion", "some-slug", "-d", "x", "--cwd", self.root)
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(self.mem) and [f for f in os.listdir(self.mem) if f != "MEMORY.md"])


class InitTests(RepoCase):
    def test_idempotent(self):
        rc, out, _ = self.run_main("init", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertIn("created docs/memory/", out)
        self.assertEqual(self.read("docs/memory/MEMORY.md"), chronicle.render_index([]))
        rc, out, _ = self.run_main("init", "--cwd", self.path("docs"))
        self.assertIn("already initialized", out)
        self.assertEqual(self.read(".gitattributes"), chronicle.UNION_LINE + "\n")

    def test_preserves_and_dedupes_gitattributes(self):
        self.write(".gitattributes", "* text=auto eol=lf\r\n*.png binary")
        self.run_main("init", "--cwd", self.root)
        self.assertEqual(self.read(".gitattributes"), "* text=auto eol=lf\r\n*.png binary\r\n%s\r\n" % chronicle.UNION_LINE)
        self.write(".gitattributes", "a b\n%s\ndocs/memory/MEMORY.md   merge=union\n%s\n" % ((chronicle.UNION_LINE,) * 2))
        rc, out, _ = self.run_main("init", "--cwd", self.root)
        self.assertIn("removed 2 duplicate", out)
        self.assertEqual(self.read(".gitattributes"), "a b\n%s\n" % chronicle.UNION_LINE)
        self.run_main("init", "--cwd", self.root)
        self.assertEqual(self.read(".gitattributes"), "a b\n%s\n" % chronicle.UNION_LINE)

    def test_root_anchored_union_line_counts(self):
        self.write(".gitattributes", "/docs/memory/MEMORY.md merge=union\n")
        rc, out, _ = self.run_main("init", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertEqual(self.read(".gitattributes"), "/docs/memory/MEMORY.md merge=union\n")
        self.write(".gitattributes", "/docs/memory/MEMORY.md merge=union\n%s\n" % chronicle.UNION_LINE)
        self.run_main("init", "--cwd", self.root)
        self.assertEqual(self.read(".gitattributes"), "/docs/memory/MEMORY.md merge=union\n")

    def test_unusable_gitattributes_is_a_clean_error(self):
        utf16 = "* text=auto\n".encode("utf-16")
        self.write(".gitattributes", utf16, mode="wb")
        rc, _, err = self.run_main("init", "--cwd", self.root)
        self.assertEqual(rc, 2)
        self.assertIn("is not UTF-8", err)
        with open(self.path(".gitattributes"), "rb") as f:
            self.assertEqual(f.read(), utf16, "left unchanged")
        os.remove(self.path(".gitattributes"))
        os.makedirs(self.path(".gitattributes"))
        rc, _, err = self.run_main("new", "decision", "some-fact", "-d", "Fact", "--cwd", self.root)
        self.assertEqual(rc, 2)
        self.assertIn("not a regular file", err)
        self.assertNotIn("Traceback", err)


# --------------------------------------------------------------------------- migrate-plan


def snapshot(top):
    state = {}
    for dirpath, dirnames, filenames in os.walk(top):
        for name in filenames:
            p = os.path.join(dirpath, name)
            with open(p, "rb") as f:
                state[os.path.relpath(p, top)] = f.read()
        for name in dirnames:
            state[os.path.relpath(os.path.join(dirpath, name), top) + "/"] = None
    return state


class MigratePlanTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.claude_dir = os.path.join(self.tmp, "claude-config")  # never read the real ~/.claude
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.claude_dir})
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.root] + list(args), check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode("utf-8")

    def make_legacy(self):
        self.write("docs/memory/UPDATE_LOG.md",
                   "# Update Log\n\nLast Updated: Monday, 03-08-2026, 9:30 pm\nLast Updated: Sunday, 02-08-2026, 6:08 am\n"
                   "\n## Entry one\n- x\n## Entry two\n- y\n## Entry three\n- z\n")
        self.write("docs/memory/PROJECT_MEMORY.md", "# Project Memory\n**Last Updated:** x\n## Decisions\n## Gotchas\n")
        for i in range(3):
            self.write("docs/memory/updates/2026-06-2%d-entry.md" % i, "entry %d\n" % i)
        self.write("docs/memory/SUPERVISION_PROTOCOL.md", "# protocol\n")
        self.write("docs/PHASE_STATUS.md", "# Phase\n")
        self.write("docs/memory/.gitkeep", "")
        self.write(".gitattributes", "* text=auto\ndocs/memory/UPDATE_LOG.md     merge=union\n"
                   "docs/memory/PROJECT_MEMORY.md merge=union\ndocs/PHASE_STATUS.md merge=union\n"
                   "src/memory_pool.c diff=cpp\n")
        self.write(".githooks/pre-push", "#!/bin/sh\npython3 .githooks/stamp-memory-date.py\ngit add docs/memory/UPDATE_LOG.md\n")
        self.write(".git/hooks/pre-commit", "#!/bin/sh\nscripts/check_memory_freshness.py --mode pre-commit\n")
        self.write(".git/hooks/pre-commit.sample", "#!/bin/sh\n# UPDATE_LOG sample-only\n")
        self.write(".claude/settings.json", '{"env": {"CLAUDE_MEMORY_FILES": "docs/memory/PROJECT_MEMORY.md"}}\n')
        self.write(".claude/hooks/session_context.py", 'emit(ROOT / "memory" / "PROJECT_MEMORY.md")\n')
        self.write(".codex/hooks.json", '{"hooks": {"SessionStart": [{"hooks": [{"statusMessage": "Loading memory"}]}]}}\n')
        self.write(".gitignore", "node_modules/\ndocs/memory/\n")
        self.write("AGENTS.md", "# Agents\n1. Read `docs/memory/PROJECT_MEMORY.md` + `docs/memory/UPDATE_LOG.md`.\nOther line\n")
        self.write("CLAUDE.md", "Update UPDATE_LOG.md after work\n")

    def test_inventory_and_checklist(self):
        self.make_legacy()
        before = snapshot(self.root)
        rc, out, _ = self.run_main("migrate-plan", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertEqual(snapshot(self.root), before, "migrate-plan must be read-only")
        for fragment in (
            "docs/memory/UPDATE_LOG.md: ",
            "3 `## ` headings, 2 `Last Updated:` lines",
            "docs/memory/PROJECT_MEMORY.md: ",
            "2 `## ` headings, 1 `Last Updated:` lines",
            "docs/memory/updates/: 3 files",
            "docs/memory/MEMORY.md: absent",
            "docs/memory/SUPERVISION_PROTOCOL.md",
            "docs/PHASE_STATUS.md",
            ".gitattributes:2: docs/memory/UPDATE_LOG.md     merge=union",
            ".gitattributes:3: docs/memory/PROJECT_MEMORY.md merge=union",
            ".githooks/pre-push:2: python3 .githooks/stamp-memory-date.py",
            ".githooks/pre-push:3: git add docs/memory/UPDATE_LOG.md",
            "pre-commit:2: scripts/check_memory_freshness.py",
            ".claude/settings.json:1:",
            ".claude/hooks/session_context.py:1:",
            ".codex/hooks.json:1:",
            ".gitignore:2: docs/memory/",
            "AGENTS.md:2: 1. Read `docs/memory/PROJECT_MEMORY.md`",
            "CLAUDE.md:1: Update UPDATE_LOG.md after work",
            "[ ] 1. Work in a sibling worktree on branch chore/memory-v2",
            "[ ] 2. Rebase onto the latest remote integration branch before migrating",
            "conflicts on AGENTS.md",
            "[ ] 3. chronicle init",
            "[ ] 5. Promote project facts from Claude auto memory (",
            "memory: absent; also other machines",
            "do not delete them",
            "read docs/memory/PROJECT_MEMORY.md fully",
            "scan the headings (or entry first lines) of docs/memory/UPDATE_LOG.md",
            "(from docs/PHASE_STATUS.md)",
            "git rm the legacy files (docs/memory/UPDATE_LOG.md, docs/memory/PROJECT_MEMORY.md, docs/memory/updates/)",
            "move out non-memory docs (docs/memory/SUPERVISION_PROTOCOL.md)",
            "Remove legacy machinery: 2 legacy .gitattributes line(s); review and remove memory gates/stampers in ",
            "(leave unrelated settings alone)",
            "ask the repo owner",
            "Replace the memory rules in AGENTS.md, CLAUDE.md",
            "[ ] 11. Verify: chronicle lint && chronicle index --check",
        ):
            self.assertIn(fragment, out)
        self.assertNotIn("sample-only", out)
        self.assertNotIn("Other line", out)
        self.assertNotIn("PHASE_STATUS.md merge=union", out)
        self.assertNotIn("memory_pool", out)
        self.assertNotIn(".gitkeep", out)
        self.assertNotIn("core.hooksPath", out)

    def test_hook_lines_capped_per_file(self):
        self.write(".githooks/pre-push", "".join("echo memory gate %d\n" % i for i in range(8)))
        rc, out, _ = self.run_main("migrate-plan", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertIn(".githooks/pre-push:5: echo memory gate 4", out)
        self.assertNotIn("echo memory gate 5", out)
        self.assertIn(".githooks/pre-push: ... 3 more matching lines", out)
        self.assertIn("memory gates/stampers in .githooks/pre-push (leave", out)

    def test_clean_repo(self):
        rc, out, _ = self.run_main("migrate-plan", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertIn("Legacy memory\n  none", out)
        self.assertIn("No ignore rules hide docs/memory.", out)
        self.assertIn("no hook or tooling files mention memory", out)

    def test_union_line_marked_keep(self):
        self.write(".gitattributes", "/docs/memory/MEMORY.md merge=union\nmemory/UPDATE_LOG.md merge=union\n")
        rc, out, _ = self.run_main("migrate-plan", "--cwd", self.root)
        self.assertIn(".gitattributes:1: /docs/memory/MEMORY.md merge=union  (keep: chronicle)", out)
        self.assertIn("Remove legacy machinery: 1 legacy .gitattributes line(s)", out)

    def test_current_store_attributes_are_not_legacy(self):
        """N4: only rules for legacy files count; the index rule with extra attributes is kept."""
        self.write(".gitattributes", "docs/memory/MEMORY.md merge=union text eol=lf\ndocs/memory/*.md text eol=lf\n"
                   "docs/memory/UPDATE_LOG.md merge=union\nmemory/updates/** -diff\n")
        rc, out, _ = self.run_main("migrate-plan", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertIn(".gitattributes:1: docs/memory/MEMORY.md merge=union text eol=lf  (keep: chronicle)\n", out)
        self.assertIn(".gitattributes:2: docs/memory/*.md text eol=lf\n", out)
        self.assertIn(".gitattributes:3: docs/memory/UPDATE_LOG.md merge=union  (legacy)\n", out)
        self.assertIn(".gitattributes:4: memory/updates/** -diff  (legacy)\n", out)
        self.assertIn("Remove legacy machinery: 2 legacy .gitattributes line(s)", out)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_real_git_ignore_rules_and_hooks_path(self):
        shutil.rmtree(self.path(".git"))
        subprocess.run(["git", "init", "-q", self.root], check=True)
        subprocess.run(["git", "-C", self.root, "config", "core.hooksPath", ".githooks"], check=True)
        self.write(".gitignore", "build/\ndocs/memory/\n!docs/memory/keep.md\n")
        self.write(".githooks/pre-commit", "#!/bin/sh\nstamp_memory\n")
        rc, out, _ = self.run_main("migrate-plan", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertEqual(out.count(".gitignore:2: docs/memory/\n"), 1)
        self.assertNotIn("keep.md", out.split("Ignore rules")[1].split("\n\n")[0])
        self.assertEqual(out.count(".githooks/pre-commit:2: stamp_memory"), 1, "hooksPath dir must be scanned once")
        self.assertNotIn("core.hooksPath is absolute", out, "a relative hooksPath is per worktree")

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_absolute_hooks_path_shared_by_worktrees(self):
        shutil.rmtree(self.path(".git"))
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".githooks/pre-push", "#!/bin/sh\nstamp_memory\n")
        self.git("add", "-A")
        self.git("-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
                 "commit", "-q", "-m", "init")
        wt = os.path.join(self.tmp, "repo-memory-v2")
        self.git("worktree", "add", wt, "-b", "chore/memory-v2")
        self.git("config", "core.hooksPath", self.path(".githooks"))
        configured = self.git("config", "--path", "--get", "core.hooksPath").strip()
        for cwd in (wt, self.root):
            rc, out, _ = self.run_main("migrate-plan", "--cwd", cwd)
            self.assertEqual(rc, 0)
            self.assertEqual(out.count("pre-push:2: stamp_memory"), 1, out)
            self.assertIn("\n  .githooks/pre-push:2: stamp_memory", out, "this worktree's copy, by relative path")
            self.assertIn("  note: core.hooksPath is absolute (%s): worktrees run the main checkout's hooks"
                          % configured, out)
        with open(os.path.join(wt, ".githooks", "pre-push"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")  # the branch removed the stamper; main still has it
        rc, out, _ = self.run_main("migrate-plan", "--cwd", wt)
        self.assertNotIn("stamp_memory", out, "the branch's copy is what the plan reports")
        self.assertIn("no hook or tooling files mention memory", out)

    def test_claude_auto_memory_listed(self):
        self.assertEqual(chronicle.claude_project_slug("/home/a/projects/MyRepo"), "-home-a-projects-MyRepo")
        self.assertEqual(chronicle.claude_project_slug("C:\\Users\\A B\\repo-0.3.2"), "C--Users-A-B-repo-0-3-2")
        auto = os.path.join(self.claude_dir, "projects", chronicle.claude_project_slug(self.root), "memory")
        os.makedirs(auto)
        for name in ("MEMORY.md", "feedback_testing.md", ".DS_Store"):
            with open(os.path.join(auto, name), "w") as f:
                f.write("x\n")
        rc, out, _ = self.run_main("migrate-plan", "--cwd", self.root)
        self.assertEqual(rc, 0)
        self.assertIn("Claude auto memory on this machine (shared by all worktrees of the repo)\n  %s: 2 files" % auto, out)
        self.assertIn("Promote project facts from Claude auto memory (%s: 2 files; " % auto, out)


# --------------------------------------------------------------------------- install


class InstallTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(os.path.join(self.home, ".codex"))
        self.settings_path = os.path.join(self.home, ".claude", "settings.json")
        self.original = {
            "model": "keep-me",
            "permissions": {"allow": ["Bash(ls)"]},
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}],
                "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}],
            },
        }
        with open(self.settings_path, "w") as f:
            json.dump(self.original, f, indent=4)
        with open(self.settings_path) as f:
            self.original_text = f.read()

    def install(self, *extra):
        return self.run_main("install", "--home", self.home, *extra)

    def load(self, *parts):
        with open(os.path.join(self.home, *parts), encoding="utf-8") as f:
            return json.load(f)

    def chronicle_handlers(self, data):
        return [h for g in data["hooks"]["SessionStart"] for h in g["hooks"] if chronicle.is_chronicle_handler(h)]

    def test_copies_skill_and_merges_hooks(self):
        rc, out, err = self.install("--hooks", "--python", "python3")
        self.assertEqual(rc, 0, out + err)
        for platform in ("claude", "codex"):
            dest = os.path.join(self.home, "." + platform, "skills", "chronicle")
            for rel in ("SKILL.md", "scripts/chronicle.py", "references/format.md",
                        "references/migrate.md", "references/agents-snippet.md"):
                self.assertTrue(os.path.isfile(os.path.join(dest, *rel.split("/"))), rel)
            for dirpath, dirnames, filenames in os.walk(dest):
                self.assertNotIn("__pycache__", dirnames)
        settings = self.load(".claude", "settings.json")
        self.assertEqual(settings["model"], "keep-me")
        self.assertEqual(settings["permissions"], self.original["permissions"])
        self.assertEqual(settings["hooks"]["PreToolUse"], self.original["hooks"]["PreToolUse"])
        self.assertEqual(settings["hooks"]["SessionStart"][0], self.original["hooks"]["SessionStart"][0])
        script = slashes(os.path.join(self.home, ".claude", "skills", "chronicle", "scripts", "chronicle.py"))
        self.assertEqual(settings["hooks"]["SessionStart"][1], {
            "matcher": "startup|resume|clear|compact|fork",
            "hooks": [{"type": "command", "command": 'python3 "%s" context' % script, "timeout": 10}],
        })
        with open(self.settings_path + ".bak-chronicle") as f:
            self.assertEqual(f.read(), self.original_text)
        codex = self.load(".codex", "hooks.json")
        codex_script = slashes(os.path.join(self.home, ".codex", "skills", "chronicle", "scripts", "chronicle.py"))
        self.assertEqual(codex, {"hooks": {"SessionStart": [{
            "matcher": "startup|resume|clear|compact",
            "hooks": [{"type": "command", "command": 'python3 "%s" context' % codex_script, "timeout": 10,
                       "additionalContextLimit": 4000}],
        }]}})
        self.assertIn("/hooks", out)

    def test_idempotent(self):
        self.install("--hooks", "--python", "python3")
        with open(self.settings_path, "rb") as f:
            first = f.read()
        hooks_json = os.path.join(self.home, ".codex", "hooks.json")
        with open(hooks_json, "rb") as f:
            first_codex = f.read()
        rc, out, _ = self.install("--hooks", "--python", "python3")
        self.assertEqual(rc, 0)
        self.assertIn("already present", out)
        with open(self.settings_path, "rb") as f:
            self.assertEqual(f.read(), first)
        with open(hooks_json, "rb") as f:
            self.assertEqual(f.read(), first_codex)
        self.assertEqual(len(self.chronicle_handlers(self.load(".claude", "settings.json"))), 1)

    def test_python_change_updates_in_place(self):
        self.install("--hooks", "--python", "python3")
        self.install("--hooks", "--python", "/usr/bin/python3.10")
        for parts in ((".claude", "settings.json"), (".codex", "hooks.json")):
            handlers = self.chronicle_handlers(self.load(*parts))
            self.assertEqual(len(handlers), 1)
            self.assertTrue(handlers[0]["command"].startswith("/usr/bin/python3.10 "))
        self.assertEqual(len(self.load(".claude", "settings.json")["hooks"]["SessionStart"]), 2)
        with open(self.settings_path + ".bak-chronicle") as f:
            self.assertEqual(f.read(), self.original_text, "the first backup (the original) is kept")
        with open(os.path.join(self.home, ".codex", "hooks.json.bak-chronicle")) as f:
            self.assertNotIn("/usr/bin/python3.10", f.read())

    def test_reinstall_keeps_group_positions(self):
        """Codex keys hook trust by position: a reinstall must not reorder SessionStart groups."""
        user_group = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo user"}]}
        old_cmd = 'python3 "/old/skills/chronicle/scripts/chronicle.py" context'
        data = {"hooks": {"SessionStart": [
            {"matcher": "startup|resume", "hooks": [{"type": "command", "command": old_cmd, "statusMessage": "mem"}]},
            user_group,
            {"hooks": [{"type": "command", "command": "echo mixed"}, {"type": "command", "command": old_cmd}]},
        ]}}
        merged = chronicle.merge_session_hook(data, chronicle.hook_handler("codex", "NEW chronicle.py context"),
                                              "startup|resume|clear|compact")
        groups = merged["hooks"]["SessionStart"]
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0], {"matcher": "startup|resume|clear|compact", "hooks": [{
            "type": "command", "command": "NEW chronicle.py context", "statusMessage": "mem", "timeout": 10,
            "additionalContextLimit": 4000}]})
        self.assertEqual(groups[1], user_group)
        self.assertEqual(groups[2], {"hooks": [{"type": "command", "command": "echo mixed"}]}, "duplicate dropped")
        self.assertEqual(data["hooks"]["SessionStart"][0]["hooks"][0]["command"], old_cmd, "input not mutated")

    def test_handler_inside_user_group_updated_in_place(self):
        old_cmd = 'python3 "/old/skills/chronicle/scripts/chronicle.py" context'
        data = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [
            {"type": "command", "command": "echo a"}, {"type": "command", "command": old_cmd},
            {"type": "command", "command": "echo b"}]}]}}
        merged = chronicle.merge_session_hook(data, chronicle.hook_handler("claude", "NEW chronicle.py context"),
                                              "startup|resume|clear|compact|fork")
        group = merged["hooks"]["SessionStart"][0]
        self.assertEqual(group["matcher"], "startup", "a user's group keeps its matcher")
        self.assertEqual([h["command"] for h in group["hooks"]], ["echo a", "NEW chronicle.py context", "echo b"])

    def test_commands_mentioning_chronicle_are_not_taken_over(self):
        """B3: ownership needs a whole command running the installed chronicle script's `context`."""
        script = "/h/.claude/skills/chronicle/scripts/chronicle.py"
        foreign = (
            "echo 'Run chronicle.py context before work'",
            'python3 "/old/chronicle.py" context',
            'echo hi && python3 "%s" context' % script,
            'python3 "%s" context; rm -rf build' % script,
            'python3 "%s" context > /tmp/memory.txt' % script,
            'echo hi\npython3 "%s" context' % script,
            'python3 "%s" lint' % script,
            'echo "%s" context' % script,
            'rm -f "%s" context' % script,
            'cat %s context' % script,
            'node "%s" context' % script,
        )
        for cmd in foreign:
            self.assertFalse(chronicle.is_chronicle_handler({"type": "command", "command": cmd}), cmd)
        for cmd in ('python3 "%s" context' % script, "/usr/bin/python3 %s context --max-bytes 6000" % script,
                    'py -3 "C:\\Users\\A\\.codex\\skills\\chronicle\\scripts\\chronicle.py" context',
                    chronicle.hook_command('"C:\\Program Files\\Python\\python.exe"',
                                           "C:\\Users\\A B\\.claude\\skills\\chronicle\\scripts\\chronicle.py",
                                           windows=True)):
            self.assertTrue(chronicle.is_chronicle_handler({"type": "command", "command": cmd}), cmd)
        reminder = {"matcher": "startup", "hooks": [{"type": "command", "command": foreign[0]}]}
        data = {"hooks": {"SessionStart": [reminder]}}
        merged = chronicle.merge_session_hook(data, chronicle.hook_handler("claude", 'python3 "%s" context' % script),
                                              chronicle.HOOK_MATCHERS["claude"])
        groups = merged["hooks"]["SessionStart"]
        self.assertEqual(groups[0], reminder, "the user's reminder is untouched")
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[1]["hooks"][0]["command"], 'python3 "%s" context' % script)

    def test_reinstall_keeps_custom_timeout_and_context_limit(self):
        """N9: a reinstall updates the command but keeps the user's timeout and additionalContextLimit."""
        self.install("--hooks", "--python", "python3")
        for parts, extra in (((".claude", "settings.json"), {"timeout": 60}),
                             ((".codex", "hooks.json"), {"timeout": 60, "additionalContextLimit": 0})):
            path = os.path.join(self.home, *parts)
            data = self.load(*parts)
            self.chronicle_handlers(data)[0].update(extra, statusMessage="mine")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        rc, out, _ = self.install("--hooks", "--python", "/usr/bin/python3.10")
        self.assertEqual(rc, 0, out)
        claude = self.chronicle_handlers(self.load(".claude", "settings.json"))[0]
        self.assertTrue(claude["command"].startswith("/usr/bin/python3.10 "))
        self.assertEqual((claude["timeout"], claude["statusMessage"]), (60, "mine"))
        self.assertNotIn("additionalContextLimit", claude)
        codex = self.chronicle_handlers(self.load(".codex", "hooks.json"))[0]
        self.assertEqual((codex["timeout"], codex["additionalContextLimit"]), (60, 0))
        self.assertTrue(codex["command"].startswith("/usr/bin/python3.10 "))
        rc, out, _ = self.install("--hooks", "--python", "/usr/bin/python3.10")
        self.assertEqual(out.count("already present"), 2, "customized values are not a change")

    def skill_dir(self, platform="claude"):
        return os.path.join(self.home, "." + platform, "skills", "chronicle")

    def customized_skill(self):
        dest = self.skill_dir()
        os.makedirs(dest)
        with open(os.path.join(dest, "custom.md"), "w") as f:
            f.write("my notes")
        return dest

    def assertSkillIntact(self, dest):
        with open(os.path.join(dest, "custom.md")) as f:
            self.assertEqual(f.read(), "my notes")
        leftovers = [n for n in os.listdir(os.path.dirname(dest)) if n != "chronicle"]
        self.assertEqual(leftovers, [], "no staging or rollback copies left behind")

    def test_failed_swap_restores_previous_skill(self):
        """B2: the old installation is moved aside, not deleted, until the new copy is in place."""
        dest = self.customized_skill()
        real_replace = os.replace

        def replace(src, dst):
            if str(src).endswith(".tmp-chronicle"):
                raise OSError(5, "simulated publish failure")
            return real_replace(src, dst)

        with mock.patch.object(chronicle.os, "replace", replace):
            rc, out, _ = self.install("--claude", "--hooks", "--python", "python3")
        self.assertEqual(rc, 1, out)
        self.assertIn("error: cannot install %s (" % dest, out)
        self.assertIn("previous installation left in place", out)
        self.assertSkillIntact(dest)
        with open(self.settings_path) as f:
            self.assertEqual(f.read(), self.original_text, "no hook for a skill that was not installed")

    def test_failed_staging_leaves_previous_skill(self):
        dest = self.customized_skill()
        with mock.patch.object(shutil, "copytree", side_effect=OSError(28, "No space left on device")):
            rc, out, _ = self.install("--claude")
        self.assertEqual(rc, 1, out)
        self.assertIn("left unchanged", out)
        self.assertSkillIntact(dest)

    def test_leftover_rollback_copy_is_never_deleted(self):
        dest = self.customized_skill()
        old = dest + ".old-chronicle"
        os.makedirs(old)
        with open(os.path.join(old, "only-copy.md"), "w") as f:
            f.write("keep")
        rc, out, _ = self.install("--claude")
        self.assertEqual(rc, 1, out)
        self.assertIn("left by an interrupted install", out)
        self.assertTrue(os.path.isfile(os.path.join(old, "only-copy.md")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "custom.md")))

    def test_successful_reinstall_leaves_no_rollback_copy(self):
        self.customized_skill()
        rc, out, _ = self.install("--claude")
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.listdir(os.path.dirname(self.skill_dir())), ["chronicle"])
        self.assertTrue(os.path.isfile(os.path.join(self.skill_dir(), "SKILL.md")))

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlinked_skill_replaced_without_touching_its_target(self):
        target = os.path.join(self.tmp, "my-skill-checkout")
        os.makedirs(target)
        with open(os.path.join(target, "custom.md"), "w") as f:
            f.write("my notes")
        os.makedirs(os.path.dirname(self.skill_dir()))
        os.symlink(target, self.skill_dir())
        rc, out, _ = self.install("--claude")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.islink(self.skill_dir()))
        self.assertTrue(os.path.isfile(os.path.join(self.skill_dir(), "SKILL.md")))
        self.assertEqual(os.listdir(target), ["custom.md"], "the link target is never deleted")

    def test_wsl_drive_home_warns_about_linux_hook_command(self):
        """B8: from WSL, --home /mnt/<drive>/... writes a Linux command into Windows settings."""
        with mock.patch.object(chronicle, "copy_skill", return_value="installed skill: x"), \
                mock.patch.object(chronicle, "apply_hook_file", return_value="wrote SessionStart hook: x"):
            lines, ok = chronicle.install("/mnt/c/Users/me", ["claude"], True, "python3")
            self.assertTrue(ok)
            self.assertTrue(lines[0].startswith("warning: /mnt/c/Users/me is a Windows drive mounted in WSL"), lines)
            self.assertIn("py -3 ", lines[0])
            for home, hooks in (("/mnt/c/Users/me", False), ("/home/me", True), ("/mnt/data/me", True)):
                lines, _ = chronicle.install(home, ["claude"], hooks, "python3")
                self.assertFalse([l for l in lines if l.startswith("warning:")], (home, hooks))

    def test_bom_settings_accepted(self):
        with open(self.settings_path, "wb") as f:
            f.write(b"\xef\xbb\xbf" + self.original_text.encode("utf-8"))
        rc, out, _ = self.install("--claude", "--hooks", "--python", "python3")
        self.assertEqual(rc, 0, out)
        settings = self.load(".claude", "settings.json")
        self.assertEqual(settings["model"], "keep-me")
        self.assertEqual(len(self.chronicle_handlers(settings)), 1)

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlinked_settings_written_through(self):
        dotfiles = os.path.join(self.tmp, "dotfiles")
        os.makedirs(dotfiles)
        target = os.path.join(dotfiles, "settings.json")
        shutil.move(self.settings_path, target)
        os.chmod(target, 0o600)
        os.symlink(target, self.settings_path)
        rc, out, _ = self.install("--claude", "--hooks", "--python", "python3")
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.islink(self.settings_path), "the link must survive")
        with open(target, encoding="utf-8") as f:
            self.assertEqual(len(self.chronicle_handlers(json.load(f))), 1)
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600, "file mode kept")
        self.assertFalse([n for n in os.listdir(dotfiles) if n != "settings.json"], "no stray files in dotfiles")
        with open(self.settings_path + ".bak-chronicle") as f:
            self.assertEqual(f.read(), self.original_text)

    def test_existing_codex_hooks_preserved(self):
        hooks_json = os.path.join(self.home, ".codex", "hooks.json")
        existing = {"description": "mine", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}],
                                                       "SessionStart": [{"matcher": "startup", "hooks": [
                                                           {"type": "command", "command": "y"}]}]}}
        with open(hooks_json, "w") as f:
            json.dump(existing, f)
        self.install("--codex", "--hooks")
        data = self.load(".codex", "hooks.json")
        self.assertEqual(data["description"], "mine")
        self.assertEqual(data["hooks"]["Stop"], existing["hooks"]["Stop"])
        self.assertEqual(data["hooks"]["SessionStart"][0], existing["hooks"]["SessionStart"][0])
        self.assertEqual(len(self.chronicle_handlers(data)), 1)
        self.assertTrue(os.path.exists(hooks_json + ".bak-chronicle"))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "skills")), "--codex only")

    def test_without_hooks_leaves_settings_alone(self):
        rc, out, _ = self.install()
        self.assertEqual(rc, 0)
        self.assertIn("--hooks", out)
        with open(self.settings_path) as f:
            self.assertEqual(f.read(), self.original_text)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".codex", "hooks.json")))

    def test_default_targets_follow_existing_dirs(self):
        shutil.rmtree(os.path.join(self.home, ".codex"))
        self.install()
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".claude", "skills", "chronicle")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".codex")))
        shutil.rmtree(os.path.join(self.home, ".claude"))
        rc, _, err = self.install()
        self.assertEqual(rc, 2)
        self.assertIn("--claude", err)

    def test_reinstall_replaces_old_skill(self):
        dest = os.path.join(self.home, ".claude", "skills", "chronicle")
        os.makedirs(dest)
        with open(os.path.join(dest, "stale.md"), "w") as f:
            f.write("v1")
        self.install("--claude")
        self.assertFalse(os.path.exists(os.path.join(dest, "stale.md")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "SKILL.md")))

    def test_invalid_settings_json_left_unchanged(self):
        with open(self.settings_path, "w") as f:
            f.write("{not json")
        rc, out, _ = self.install("--claude", "--hooks")
        self.assertEqual(rc, 1)
        self.assertIn("left unchanged", out)
        with open(self.settings_path) as f:
            self.assertEqual(f.read(), "{not json")

    def test_installed_script_runs_hook(self):
        self.install("--claude", "--hooks", "--python", sys.executable)
        self.add_memory("installed-fact", description="Installed copy works")
        self.reindex()
        handler = self.chronicle_handlers(self.load(".claude", "settings.json"))[0]
        r = subprocess.run(handler["command"], shell=True, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Installed copy works", r.stdout.decode("utf-8"))

    def test_windows_hook_command_uses_forward_slashes(self):
        cmd = chronicle.hook_command("py -3", "C:\\Users\\A B\\.claude\\skills\\chronicle\\scripts\\chronicle.py",
                                     windows=True)
        self.assertEqual(cmd, 'py -3 "C:/Users/A B/.claude/skills/chronicle/scripts/chronicle.py" context')
        self.assertTrue(chronicle.is_chronicle_handler({"command": cmd}))

    def test_interpreter_path_with_spaces_is_quoted(self):
        spaced = os.path.join(self.tmp, "Python Dir", "python")
        os.makedirs(os.path.dirname(spaced))
        with open(spaced, "w") as f:
            f.write("")
        cmd = chronicle.hook_command(spaced, "/x/chronicle.py", windows=False)
        self.assertEqual(cmd, '"%s" "/x/chronicle.py" context' % spaced)
        self.assertEqual(chronicle.hook_command("py -3", "/x/chronicle.py", windows=False), 'py -3 "/x/chronicle.py" context')


# --------------------------------------------------------------------------- docs


FORMAT_MD = os.path.join(os.path.dirname(SCRIPT), os.pardir, "references", "format.md")
SKILL_MD = os.path.join(os.path.dirname(SCRIPT), os.pardir, "SKILL.md")


class DocsTests(RepoCase):
    def format_md(self):
        with open(FORMAT_MD, encoding="utf-8") as f:
            return f.read()

    def test_skill_paths_cover_both_agents_on_every_shell(self):
        """B8: Windows rows list the .codex install too, not only .claude."""
        with open(SKILL_MD, encoding="utf-8") as f:
            skill = f.read()
        self.assertLessEqual(len(skill.splitlines()), 130)
        paths = skill.split("## Paths", 1)[1]
        for home in ("%USERPROFILE%\\", "$env:USERPROFILE\\"):
            for agent in (".claude", ".codex"):
                self.assertIn('py -3 "%s%s\\skills\\chronicle\\scripts\\chronicle.py" <command>' % (home, agent), paths)
        for agent in (".claude", ".codex"):
            self.assertIn("py -3 ~/%s/skills/chronicle/scripts/chronicle.py <command>" % agent, paths)
            self.assertIn("python3 ~/%s/skills/chronicle/scripts/chronicle.py <command>" % agent, paths)
        self.assertIn("/mnt/", paths, "cross-OS install from WSL is called out")

    def test_format_md_shows_the_exact_index_header(self):
        self.assertIn("```\n" + chronicle.INDEX_HEADER + "\n## Status\n", self.format_md())

    def test_good_examples_lint_clean(self):
        good = self.format_md().split("## Good examples", 1)[1].split("## Bad examples", 1)[0]
        examples = re.findall(r"`docs/memory/([a-z0-9-]+)\.md`\n```\n(.*?)```", good, re.S)
        self.assertEqual(len(examples), 3)
        names = set(name for name, _ in examples) | {"contract-sessions-table"}
        for name, text in examples:
            m = chronicle.read_memory(self.write("docs/memory/%s.md" % name, text), name)
            updated = datetime.datetime.strptime(m.meta["updated"], "%Y-%m-%d").date()
            self.assertEqual(chronicle.lint_memory(m, names, updated), [], name)


if __name__ == "__main__":
    unittest.main()
