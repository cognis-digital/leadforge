"""Smoke + behavior tests for LEADFORGE (stdlib unittest, no network)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leadforge import Engine, LeadForgeError, TOOL_NAME, TOOL_VERSION  # noqa: E402
from leadforge.cli import main  # noqa: E402
from leadforge.core import _now  # noqa: E402


class TempDB(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.path)  # engine treats missing file as empty

    def tearDown(self):
        for p in (self.path, self.path + ".tmp"):
            if os.path.exists(p):
                os.remove(p)


class EngineTests(TempDB):
    def test_metadata(self):
        self.assertEqual(TOOL_NAME, "leadforge")
        self.assertTrue(TOOL_VERSION)

    def test_add_and_persist(self):
        eng = Engine(self.path)
        lead = eng.add_lead("Ada Lovelace", "ada@analytical.io", "AE", 5000)
        self.assertEqual(lead.stage, "new")
        eng.save()
        eng2 = Engine(self.path)
        self.assertEqual(eng2.get(lead.id).email, "ada@analytical.io")

    def test_invalid_email(self):
        eng = Engine(self.path)
        with self.assertRaises(LeadForgeError):
            eng.add_lead("Bad", "not-an-email")

    def test_duplicate_email(self):
        eng = Engine(self.path)
        eng.add_lead("A", "x@y.com")
        with self.assertRaises(LeadForgeError):
            eng.add_lead("B", "X@Y.COM")

    def test_stage_movement_and_close_guard(self):
        eng = Engine(self.path)
        l = eng.add_lead("C", "c@d.com", value=1000)
        eng.move(l.id, "qualified")
        eng.move(l.id, "won")
        with self.assertRaises(LeadForgeError):
            eng.move(l.id, "proposal")
        eng.move(l.id, "new")  # reopen allowed

    def test_sequence_schedule_and_send(self):
        eng = Engine(self.path)
        l = eng.add_lead("D", "d@e.com")
        start = _now()
        eng.enroll(l.id, "cold-outreach", start=start)
        self.assertEqual(len(eng.due_steps(start)), 1)
        sent = eng.send_due(start)
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(eng.due_steps(start)), 0)
        self.assertEqual(len(eng.due_steps(start + timedelta(days=3))), 1)

    def test_sequence_completes(self):
        eng = Engine(self.path)
        l = eng.add_lead("E", "e@f.com")
        t = _now()
        eng.enroll(l.id, "cold-outreach", start=t)
        for offset in (0, 3, 7, 14):
            eng.send_due(t + timedelta(days=offset))
        self.assertIsNone(eng.get(l.id).sequence)

    def test_cannot_enroll_closed(self):
        eng = Engine(self.path)
        l = eng.add_lead("F", "f@g.com")
        eng.move(l.id, "lost")
        with self.assertRaises(LeadForgeError):
            eng.enroll(l.id, "cold-outreach")

    def test_pipeline_metrics(self):
        eng = Engine(self.path)
        a = eng.add_lead("A", "a@a.com", value=100)
        b = eng.add_lead("B", "b@b.com", value=200)
        eng.move(a.id, "won")
        eng.move(b.id, "lost")
        p = eng.pipeline()
        self.assertEqual(p["total_leads"], 2)
        self.assertEqual(p["won_value"], 100.0)
        self.assertEqual(p["win_rate"], 0.5)


class CliTests(TempDB):
    def _run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--db", self.path, *argv])
        return rc, buf.getvalue()

    def test_cli_flow_json(self):
        rc, out = self._run("--format", "json", "add", "Grace Hopper",
                            "grace@navy.mil", "--value", "9000")
        self.assertEqual(rc, 0)
        lead = json.loads(out)
        rc, out = self._run("enroll", lead["id"])
        self.assertEqual(rc, 0)
        rc, out = self._run("--format", "json", "due")
        self.assertEqual(len(json.loads(out)), 1)
        rc, out = self._run("--format", "json", "pipeline")
        self.assertEqual(json.loads(out)["total_leads"], 1)

    def test_cli_table_does_not_crash(self):
        self._run("add", "X", "x@x.com", "--value", "5")
        rc, out = self._run("--format", "table", "pipeline")
        self.assertEqual(rc, 0)
        self.assertIn("Win-rate", out)

    def test_cli_error_nonzero(self):
        rc = main(["--db", self.path, "move", "nope", "won"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
