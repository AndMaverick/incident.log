import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from incident_log import Register, calibration, percentile, repeats
from incident_log.cli import main
from incident_log.stats import Summary

T0 = datetime(2026, 3, 1, 9, 0)


def h(n):
    return timedelta(hours=n)


def seeded():
    reg = Register()
    # A: SEV1, acked in 10 min (target 15), mitigated in 2 h (target 1), resolved in 3 h (target 4); began 1 h before it was recorded
    reg.open("A", "refund hallucination", 5, 4, 2, T0, category="hallucination", system="assistant", occurred=T0 - h(1), detected_by="customer")
    reg.acknowledge("A", T0 + h(1 / 6))
    reg.mitigate("A", T0 + h(2))
    reg.resolve("A", T0 + h(3), "stale index", "re-indexed")
    # B: SEV3, acked in 2 h (target 8), resolved in 10 h (target 72), found by monitoring
    reg.open("B", "slow", 2, 3, 3, T0 + h(24), category="latency", system="assistant", detected_by="monitor")
    reg.acknowledge("B", T0 + h(26))
    reg.resolve("B", T0 + h(34))
    # C: SEV1, same system and failure mode as A, ten days later; still open and never acknowledged
    reg.open("C", "refund hallucination again", 5, 4, 2, T0 + timedelta(days=10), category="hallucination", system="assistant", detected_by="user")
    return reg


class PercentileTests(unittest.TestCase):
    def test_percentile_by_hand(self):
        self.assertEqual(percentile([1, 2, 3, 4, 10], 50), 3)
        self.assertAlmostEqual(percentile([1, 2, 3, 4, 10], 90), 7.6)
        self.assertEqual(percentile([5], 99), 5)
        with self.assertRaises(ValueError):
            percentile([], 50)
        self.assertIsNone(Summary.of([]))


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.reg = seeded()
        self.now = T0 + timedelta(days=11)
        self.m = self.reg.metrics(self.now)

    def test_counts(self):
        self.assertEqual((self.m.incidents, self.m.open), (3, 1))
        self.assertEqual(self.m.by_severity, {"SEV1": 2, "SEV2": 0, "SEV3": 1, "SEV4": 0})
        self.assertEqual(self.m.by_category, {"hallucination": 2, "latency": 1})

    def test_times_in_hours(self):
        self.assertAlmostEqual(self.m.mttd.mean, 1.0)
        self.assertAlmostEqual(self.m.mtta.mean, (1 / 6 + 2) / 2)
        self.assertAlmostEqual(self.m.mttm.mean, (2 + 10) / 2)  # B was resolved without a mitigation record: resolving implies it
        self.assertAlmostEqual(self.m.mttr.mean, (3 + 10) / 2)

    def test_target_attainment(self):
        # acknowledge: A met, B met, C never acknowledged and long past 15 min -> 2 of 3
        self.assertEqual(self.m.sla["acknowledge"], (2, 3))
        # mitigate: A took 2 h against 1 h (missed), B 10 h against 36 h (met), C overdue -> 1 of 3
        self.assertEqual(self.m.sla["mitigate"], (1, 3))
        # resolve: A met, B met, C overdue
        self.assertEqual(self.m.sla["resolve"], (2, 3))
        self.assertAlmostEqual(self.m.attainment("resolve") or 0, 2 / 3)

    def test_detection_sources(self):
        self.assertEqual(self.m.detected_by, {"customer": 1, "monitor": 1, "user": 1})
        self.assertAlmostEqual(self.m.external_detection_share or 0, 2 / 3)

    def test_repeats_find_the_failure_that_came_back(self):
        self.assertEqual(self.m.repeats, [("assistant", "hallucination", ["A", "C"])])

    def test_window_filters_by_opening_time(self):
        m = self.reg.metrics(self.now, since=T0 + h(12), until=T0 + h(48))
        self.assertEqual(m.incidents, 1)

    def test_action_counts(self):
        self.reg.add_action("A", "x", "maria", T0 + h(5))
        self.reg.add_action("A", "y", "maria", T0 + h(500))
        self.reg.complete_action("A", "A2", T0 + h(6))
        m = self.reg.metrics(self.now)
        self.assertEqual((m.actions_done, m.actions_total, m.actions_overdue), (1, 2, 1))

    def test_empty_register(self):
        m = Register().metrics(T0)
        self.assertEqual((m.incidents, m.mttr, m.external_detection_share, m.reopen_rate), (0, None, None, 0.0))
        self.assertIsNone(m.attainment("resolve"))

    def test_repeat_window(self):
        reg = seeded()
        self.assertEqual(repeats(list(reg.incidents.values()), window_days=5), [])
        self.assertEqual(len(repeats(list(reg.incidents.values()), window_days=15)), 1)

    def test_calibration(self):
        c = calibration(self.reg)
        self.assertEqual(c["SEV1"]["n"], 2)
        self.assertAlmostEqual(c["SEV1"]["mean_hours_to_resolve"], 3.0)
        self.reg.reclassify("C", "SEV2", T0 + timedelta(days=10, hours=1))
        self.assertEqual(calibration(self.reg)["SEV1"]["lowered"], 1)


class PostmortemTests(unittest.TestCase):
    def test_sections_and_original_content(self):
        reg = seeded()
        text = reg.postmortem("A")
        for needle in ("# Postmortem: refund hallucination", "SEV1 (risk score 80)", "stale index", "re-indexed", "## Timeline",
                       "## Response against targets", "Detected by: customer", "recorded 1.0 h later", "- [ ] Add a detection", "- [ ] Add a regression case"):
            self.assertIn(needle, text)

    def test_targets_table_marks_a_miss(self):
        text = seeded().postmortem("A")
        self.assertIn("| mitigate | 1.0 h | 2.0 h | no |", text)
        self.assertIn("| resolve | 4.0 h | 3.0 h | yes |", text)

    def test_gaps_name_what_is_missing(self):
        reg = seeded()
        gaps = reg.gaps("A")
        self.assertIn("impact is not described", gaps)
        self.assertIn("no follow-up to detect this failure sooner", gaps)
        self.assertIn("no regression case added to the eval suite", gaps)
        self.assertIn("no summary of what happened", gaps)

    def test_complete_postmortem_has_no_gaps(self):
        reg = seeded()
        i = reg.get("A")
        i.impact, i.description = "14 customers promised refunds", "The assistant quoted an old policy"
        reg.add_action("A", "Alert on stale retrieval", "maria", T0 + h(100), "detection")
        reg.add_action("A", "Eval case", "maria", T0 + h(100), "regression_case", "support/refund-01")
        self.assertEqual(reg.gaps("A"), [])
        self.assertNotIn("## Open gaps", reg.postmortem("A"))

    def test_non_output_failures_do_not_need_a_regression_case(self):
        reg = seeded()
        self.assertNotIn("no regression case added to the eval suite", reg.gaps("B"))

    def test_actions_without_owner_or_date_are_flagged(self):
        reg = seeded()
        reg.add_action("A", "vague", kind="prevention")
        self.assertIn("action A1 has no owner", reg.gaps("A"))
        self.assertIn("action A1 has no due date", reg.gaps("A"))

    def test_open_incident_and_unfiled_duty(self):
        reg = seeded()
        self.assertIn("incident is still open", reg.gaps("C"))
        reg.track("A", "gdpr_33")
        self.assertIn("reporting duty gdpr_33 has not been filed", reg.gaps("A"))
        self.assertIn("## Reporting duties", reg.postmortem("A"))

    def test_pipes_in_text_do_not_break_the_table(self):
        reg = seeded()
        reg.note("A", T0 + h(1), "a | b")
        self.assertIn("a \\| b", reg.postmortem("A"))


class ReportTests(unittest.TestCase):
    def test_weekly_report(self):
        reg = seeded()
        reg.add_action("A", "late", "maria", T0 + h(5))
        reg.track("C", "gdpr_33", aware=T0 + timedelta(days=10))
        text = reg.report(T0 + timedelta(days=11), days=14)
        self.assertIn("3 incidents opened (2 SEV1, 1 SEV3); 1 still open", text)
        self.assertIn("## Late now", text)
        self.assertIn("C SEV1 acknowledge", text)
        self.assertIn("## Came back", text)
        self.assertIn("assistant / hallucination: A, C", text)
        self.assertIn("GDPR personal data breach", text)
        self.assertIn("1 overdue", text)


class StoreTests(unittest.TestCase):
    def test_round_trip_keeps_everything(self):
        reg = seeded()
        reg.add_action("A", "x", "maria", T0 + h(5), "detection", "ref")
        reg.pause("C", T0 + timedelta(days=10, hours=1))
        reg.track("A", "gdpr_33")
        reg.reclassify("B", "SEV2", T0 + h(30))
        back = Register.from_dict(json.loads(json.dumps(reg.to_dict())))
        self.assertEqual(back.to_dict(), reg.to_dict())
        self.assertEqual(back.get("C").pauses[0][1], None)
        self.assertEqual(back.get("B").initial_severity, "SEV3")

    def test_save_and_load_file(self):
        reg = seeded()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.json")
            reg.save(path)
            self.assertEqual(sorted(os.listdir(d)), ["r.json"])  # no temp file left behind
            self.assertEqual(Register.load(path).to_dict(), reg.to_dict())

    def test_unsupported_version(self):
        with self.assertRaises(ValueError):
            Register.from_dict({"version": 7, "incidents": []})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "i.json")

    def run_cli(self, at, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", self.db, "--at", at, *argv])
        return code, out.getvalue(), err.getvalue()

    def test_full_flow(self):
        code, out, _ = self.run_cli("2026-03-02T08:00", "open", "INC-1", "bad answer", "--impact", "5", "--likelihood", "4", "--detectability", "2",
                                    "--category", "hallucination", "--system", "bot", "--detected-by", "customer")
        self.assertEqual(code, 0)
        self.assertIn("opened as SEV1 (risk score 80); resolve by 2026-03-02 12:00", out)
        code, out, _ = self.run_cli("2026-03-02T09:00", "status")
        self.assertEqual(code, 1)  # not acknowledged within 15 minutes
        self.assertIn("LATE  INC-1 acknowledge", out)
        self.assertEqual(self.run_cli("2026-03-02T09:00", "status", "--no-fail")[0], 0)
        self.run_cli("2026-03-02T09:01", "ack", "INC-1", "--by", "maria")
        self.run_cli("2026-03-02T09:30", "mitigate", "INC-1", "--note", "pinned")
        code, out, _ = self.run_cli("2026-03-02T10:00", "status")
        self.assertEqual(code, 0)
        self.assertNotIn("LATE", out)
        self.run_cli("2026-03-02T11:00", "resolve", "INC-1", "--cause", "stale index", "--fix", "re-indexed")
        code, out, _ = self.run_cli("2026-03-02T12:00", "gaps", "INC-1")
        self.assertEqual(code, 1)
        self.assertIn("impact is not described", out)
        code, out, _ = self.run_cli("2026-03-02T12:00", "postmortem", "INC-1")
        self.assertIn("# Postmortem: bad answer", out)
        code, out, _ = self.run_cli("2026-03-02T12:00", "metrics")
        self.assertIn("time to resolve", out)
        self.assertIn("100%", out)
        self.assertIn("INC-1", self.run_cli("2026-03-02T12:00", "list", "--all")[1])

    def test_action_track_submit_and_status_gate(self):
        self.run_cli("2026-03-02T08:00", "open", "I", "leak", "--impact", "4", "--likelihood", "3", "--detectability", "2", "--personal-data")
        code, out, _ = self.run_cli("2026-03-02T08:05", "track", "I", "gdpr_33")
        self.assertIn("due 2026-03-05 08:00", out)
        self.run_cli("2026-03-02T08:06", "ack", "I")
        self.run_cli("2026-03-02T08:07", "mitigate", "I")
        self.run_cli("2026-03-02T08:08", "resolve", "I", "--cause", "c", "--fix", "f")
        self.assertEqual(self.run_cli("2026-03-04T08:00", "status")[0], 0)  # duty open, not yet due
        code, out, _ = self.run_cli("2026-03-06T08:00", "status")
        self.assertEqual(code, 1)
        self.assertIn("DUTY  I:", out)
        self.run_cli("2026-03-06T08:10", "submit", "I", "gdpr_33")
        self.assertEqual(self.run_cli("2026-03-06T09:00", "status")[0], 0)
        code, out, _ = self.run_cli("2026-03-06T09:00", "action", "I", "Mask card numbers", "--owner", "dev", "--due", "2026-03-10", "--kind", "prevention")
        self.assertIn("I A1:", out)
        self.assertEqual(self.run_cli("2026-03-07T09:00", "done", "I", "A1")[0], 0)

    def test_errors_are_clean(self):
        code, _, err = self.run_cli("2026-03-02T08:00", "ack", "nope")
        self.assertEqual(code, 2)
        self.assertIn("no incident 'nope'", err)
        self.run_cli("2026-03-02T08:00", "open", "X", "t", "--impact", "1", "--likelihood", "1", "--detectability", "1")
        self.assertEqual(self.run_cli("2026-03-02T08:00", "open", "X", "t", "--impact", "1", "--likelihood", "1", "--detectability", "1")[0], 2)
        self.assertEqual(self.run_cli("2026-03-02T08:00", "open", "Y", "t", "--impact", "9", "--likelihood", "1", "--detectability", "1")[0], 2)
        self.assertEqual(self.run_cli("2026-03-02T08:00", "track", "X", "nope")[0], 2)

    def test_obligations_listing(self):
        code, out, _ = self.run_cli("2026-03-02T08:00", "obligations")
        self.assertEqual(code, 0)
        self.assertIn("gdpr_33", out)
        self.assertIn("EU AI Act Art. 73(3)", out)


if __name__ == "__main__":
    unittest.main()
