import unittest
from datetime import datetime, timedelta

from incident_log import Register, risk_score, severity

T0 = datetime(2026, 3, 1, 9, 0)


class ScoringTests(unittest.TestCase):
    def test_score_and_bands(self):
        self.assertEqual(risk_score(5, 4, 2), 80)
        self.assertEqual([severity(s) for s in (80, 30, 27, 4)], ["SEV1", "SEV2", "SEV3", "SEV4"])

    def test_detectability_lowers_risk(self):
        self.assertLess(risk_score(4, 4, 5), risk_score(4, 4, 1))

    def test_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            risk_score(6, 1, 1)


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.reg = Register()
        self.reg.open("A", "Hallucinated refund policy", 5, 4, 2, T0)   # SEV1, 4h SLA
        self.reg.open("B", "Slow responses", 2, 3, 3, T0)               # SEV4? 2*3*3=18 -> SEV3

    def test_duplicate_id_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.open("A", "again", 1, 1, 1, T0)

    def test_sla_breach_detection(self):
        self.assertEqual(self.reg.breached(T0 + timedelta(hours=3)), [])
        self.assertEqual([i.id for i in self.reg.breached(T0 + timedelta(hours=5))], ["A"])
        self.assertEqual([i.id for i in self.reg.breached(T0 + timedelta(hours=80))], ["A", "B"])

    def test_resolved_incidents_do_not_breach(self):
        self.reg.resolve("A", T0 + timedelta(hours=2))
        self.assertEqual(self.reg.breached(T0 + timedelta(hours=10)), [])

    def test_mttr(self):
        self.assertIsNone(self.reg.mttr_hours())
        self.reg.resolve("A", T0 + timedelta(hours=2))
        self.reg.resolve("B", T0 + timedelta(hours=6))
        self.assertAlmostEqual(self.reg.mttr_hours(), 4.0)

    def test_postmortem_contains_key_sections(self):
        self.reg.resolve("A", T0 + timedelta(hours=2), cause="Stale policy doc", fix="Retrieval filter")
        text = self.reg.postmortem("A")
        for needle in ("# Postmortem: Hallucinated refund policy", "SEV1", "Stale policy doc", "Retrieval filter"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
