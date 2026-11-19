import unittest
from datetime import datetime, timedelta, timezone

from incident_log import OBLIGATIONS, Bands, Obligation, Policy, Register, deadline_after, risk_score, severity

T0 = datetime(2026, 3, 1, 9, 0)


def h(n):
    return timedelta(hours=n)


class ScoringTests(unittest.TestCase):
    def test_scores_by_hand(self):
        self.assertEqual(risk_score(1, 1, 5), 1)
        self.assertEqual(risk_score(5, 5, 1), 125)
        self.assertEqual(risk_score(3, 4, 2), 48)

    def test_rejects_non_integers_and_out_of_range(self):
        for bad in ((0, 1, 1), (1, 6, 1), (1, 1, True), (2.5, 1, 1)):
            with self.assertRaises(ValueError):
                risk_score(*bad)

    def test_band_edges(self):
        self.assertEqual([severity(s) for s in (60, 59, 30, 29, 12, 11)], ["SEV1", "SEV2", "SEV2", "SEV3", "SEV3", "SEV4"])

    def test_custom_bands_change_severity(self):
        reg = Register(Policy(bands=Bands(sev1=40, sev2=20, sev3=8)))
        self.assertEqual(reg.open("A", "t", 3, 4, 2, T0).severity, "SEV1")  # 48 >= 40
        with self.assertRaises(ValueError):
            Bands(sev1=10, sev2=20, sev3=5)


class PauseClockTests(unittest.TestCase):
    def test_deadline_without_pauses(self):
        self.assertEqual(deadline_after(T0, 4, []), T0 + h(4))

    def test_pause_extends_the_deadline_by_its_length(self):
        pauses = [(T0 + h(1), T0 + h(2.5))]
        self.assertEqual(deadline_after(T0, 4, pauses), T0 + h(5.5))

    def test_pause_after_the_deadline_is_ignored(self):
        self.assertEqual(deadline_after(T0, 4, [(T0 + h(6), T0 + h(8))]), T0 + h(4))

    def test_pause_that_pushes_the_deadline_over_a_later_pause(self):
        pauses = [(T0 + h(1), T0 + h(2)), (T0 + h(4.5), T0 + h(5))]
        # 4 running hours: 1 + (pause 1) + 3 more = T0+5h reached after the first pause, so the second (4.5) now counts too
        self.assertEqual(deadline_after(T0, 4, pauses), T0 + h(5.5))

    def test_open_pause_means_no_deadline(self):
        self.assertIsNone(deadline_after(T0, 4, [(T0 + h(1), None)]))

    def test_register_pause_resume_cycle(self):
        reg = Register()
        i = reg.open("A", "t", 5, 4, 2, T0)  # SEV1, 4 h
        reg.pause("A", T0 + h(1))
        self.assertIsNone(reg.policy.deadline(i, "resolve"))
        self.assertEqual(reg.breached(T0 + h(50)), [])  # paused incidents are not late
        reg.resume("A", T0 + h(3))
        self.assertEqual(reg.policy.deadline(i, "resolve"), T0 + h(6))
        with self.assertRaises(ValueError):
            reg.resume("A", T0 + h(4))
        reg.pause("A", T0 + h(4))
        with self.assertRaises(ValueError):
            reg.pause("A", T0 + h(5))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.reg = Register()
        self.a = self.reg.open("A", "Hallucinated refund policy", 5, 4, 2, T0)

    def test_event_log_follows_the_incident(self):
        self.reg.acknowledge("A", T0 + h(0.2), "maria")
        self.reg.mitigate("A", T0 + h(1), "pinned the index")
        self.reg.resolve("A", T0 + h(3), "stale index", "re-indexed")
        self.assertEqual([e.kind for e in self.a.events], ["opened", "acknowledged", "mitigated", "resolved"])

    def test_acknowledge_is_idempotent_and_keeps_the_first_time(self):
        self.reg.acknowledge("A", T0 + h(0.2))
        self.reg.acknowledge("A", T0 + h(2))
        self.assertEqual(self.a.acknowledged, T0 + h(0.2))

    def test_times_before_opening_are_rejected(self):
        for call in (self.reg.acknowledge, self.reg.mitigate):
            with self.assertRaises(ValueError):
                call("A", T0 - h(1))
        with self.assertRaises(ValueError):
            self.reg.resolve("A", T0 - h(1))
        with self.assertRaises(ValueError):
            self.reg.open("B", "t", 1, 1, 1, T0, occurred=T0 + h(1))

    def test_unknown_incident_has_a_clear_error(self):
        with self.assertRaises(KeyError) as cm:
            self.reg.resolve("nope", T0)
        self.assertIn("no incident 'nope'", str(cm.exception))

    def test_reopen_and_reclassify(self):
        with self.assertRaises(ValueError):
            self.reg.reopen("A", T0 + h(1))
        self.reg.resolve("A", T0 + h(2))
        self.reg.reopen("A", T0 + h(3), "came back")
        self.assertIsNone(self.a.resolved)
        self.assertEqual(self.a.reopened, 1)
        self.reg.reclassify("A", "SEV3", T0 + h(4), "narrower than thought")
        self.assertEqual((self.a.severity, self.a.initial_severity), ("SEV3", "SEV1"))
        with self.assertRaises(ValueError):
            self.reg.reclassify("A", "SEV9", T0)

    def test_actions(self):
        act = self.reg.add_action("A", "Add a regression case", "maria", T0 + h(48), "regression_case", "support/refund-01")
        self.assertEqual(act.id, "A1")
        self.assertTrue(act.overdue(T0 + h(49)))
        self.reg.complete_action("A", "A1", T0 + h(10))
        self.assertFalse(act.overdue(T0 + h(49)))
        with self.assertRaises(ValueError):
            self.reg.add_action("A", "x", kind="wish")
        with self.assertRaises(KeyError):
            self.reg.complete_action("A", "A9", T0)


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.reg = Register()
        self.reg.open("A", "sev1", 5, 4, 2, T0)  # SEV1: ack 15 min, mitigate 1 h, resolve 4 h
        self.reg.open("B", "sev3", 2, 3, 3, T0)  # SEV3

    def test_breaches_list_each_missed_stage(self):
        stages = [(b.incident.id, b.stage) for b in self.reg.breaches(T0 + h(5))]
        self.assertEqual(stages, [("A", "acknowledge"), ("A", "mitigate"), ("A", "resolve")])  # most overdue first

    def test_completed_stages_do_not_breach(self):
        self.reg.acknowledge("A", T0 + h(0.1))
        self.reg.mitigate("A", T0 + h(0.5))
        self.assertEqual([(b.incident.id, b.stage) for b in self.reg.breaches(T0 + h(5))], [("A", "resolve")])

    def test_original_breached_contract(self):
        self.assertEqual(self.reg.breached(T0 + h(3)), [])
        self.assertEqual([i.id for i in self.reg.breached(T0 + h(5))], ["A"])
        self.assertEqual([i.id for i in self.reg.breached(T0 + h(80))], ["A", "B"])

    def test_custom_policy_and_validation(self):
        p = Policy(resolve_hours={"SEV1": 2, "SEV2": 24, "SEV3": 72, "SEV4": 168})
        reg = Register(p)
        reg.open("A", "t", 5, 4, 2, T0)
        self.assertEqual([i.id for i in reg.breached(T0 + h(3))], ["A"])
        with self.assertRaises(ValueError):
            Policy(resolve_hours={"SEV1": 4})
        with self.assertRaises(ValueError):
            Policy(mitigate_hours={"SEV1": 10, "SEV2": 24, "SEV3": 72, "SEV4": 168})  # mitigate after resolve

    def test_policy_round_trips_through_a_dict(self):
        p = Policy(bands=Bands(50, 25, 10))
        self.assertEqual(Policy.from_dict(p.to_dict()).to_dict(), p.to_dict())


class EscalationTests(unittest.TestCase):
    def setUp(self):
        self.reg = Register()
        self.reg.open("A", "sev1", 5, 4, 2, T0)

    def roles(self, hours):
        return [e.role for e in self.reg.escalations(T0 + h(hours))]

    def test_ladder_climbs_with_age(self):
        self.assertEqual(self.roles(0), ["on-call"])
        self.assertEqual(self.roles(1.5), ["on-call", "engineering lead"])  # 25% of 4 h is 1 h
        self.assertEqual(self.roles(2.5), ["on-call", "engineering lead", "executive sponsor"])

    def test_recorded_escalations_are_not_repeated(self):
        self.reg.escalate("A", T0, "on-call")
        self.assertEqual(self.roles(1.5), ["engineering lead"])

    def test_mitigation_stops_the_ladder(self):
        self.reg.mitigate("A", T0 + h(0.5))
        self.assertEqual(self.roles(3), [])

    def test_a_pause_delays_escalation(self):
        self.reg.pause("A", T0 + h(0.5))
        self.reg.resume("A", T0 + h(2.5))
        self.assertNotIn("engineering lead", self.roles(2.6))  # 25% of the *running* clock is 3 h after the pause
        self.assertIn("engineering lead", self.roles(3.1))


class ObligationTests(unittest.TestCase):
    def setUp(self):
        self.reg = Register()
        self.reg.open("A", "t", 4, 3, 2, T0, personal_data=True)

    def test_builtin_clocks_match_their_sources(self):
        self.assertEqual(OBLIGATIONS["gdpr_33"].hours, 72)
        self.assertEqual(OBLIGATIONS["ai_act_73_general"].hours, 15 * 24)
        self.assertEqual(OBLIGATIONS["ai_act_73_widespread"].hours, 48)
        self.assertEqual(OBLIGATIONS["ai_act_73_death"].hours, 10 * 24)
        self.assertEqual((OBLIGATIONS["nis2_early_warning"].hours, OBLIGATIONS["nis2_notification"].hours), (24, 72))

    def test_gdpr_clock_runs_from_awareness_not_from_opening(self):
        self.reg.track("A", "gdpr_33", aware=T0 + h(5))
        due = self.reg.obligations_due(T0 + h(6))[0]
        self.assertEqual(due.deadline, T0 + h(77))
        self.assertEqual(due.status, "open")
        self.assertEqual(due.remaining(T0 + h(6)), h(71))

    def test_overdue_filed_and_filed_late(self):
        self.reg.track("A", "gdpr_33")
        self.assertEqual(self.reg.obligations_due(T0 + h(80))[0].status, "overdue")
        self.reg.submit("A", "gdpr_33", T0 + h(80))
        self.assertEqual(self.reg.obligations_due(T0 + h(90)), [])
        self.assertEqual(self.reg.obligations_due(T0 + h(90), include_filed=True)[0].status, "filed late")
        self.reg.submit("A", "gdpr_33", T0 + h(60))
        self.assertEqual(self.reg.obligations_due(T0 + h(90), include_filed=True)[0].status, "filed")

    def test_nis2_final_report_runs_from_the_notification(self):
        for key in ("nis2_notification", "nis2_final"):
            self.reg.track("A", key)
        i = self.reg.get("A")
        self.assertEqual(self.reg.obligation_deadline(i, "nis2_final"), T0 + h(72) + h(720))  # not yet filed: from its due time
        self.reg.submit("A", "nis2_notification", T0 + h(50))
        self.assertEqual(self.reg.obligation_deadline(i, "nis2_final"), T0 + h(50) + h(720))

    def test_custom_obligation_and_unknown_key(self):
        self.reg.define_obligation(Obligation("contract_acme", "Tell Acme within 24 hours", 24, "Acme MSA 9.2"))
        self.reg.track("A", "contract_acme")
        self.assertEqual(self.reg.obligations_due(T0)[0].deadline, T0 + h(24))
        with self.assertRaises(KeyError):
            self.reg.track("A", "made_up")
        with self.assertRaises(KeyError):
            self.reg.submit("A", "gdpr_33", T0)

    def test_overdue_sorts_first(self):
        self.reg.open("B", "t", 4, 3, 2, T0)
        self.reg.track("A", "ai_act_73_general")
        self.reg.track("B", "gdpr_33")
        self.assertEqual([d.incident.id for d in self.reg.obligations_due(T0 + h(100))], ["B", "A"])


class AwareTimeTests(unittest.TestCase):
    def test_timezone_aware_times_work_throughout(self):
        t0 = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
        reg = Register()
        reg.open("A", "t", 5, 4, 2, t0)
        self.assertEqual([i.id for i in reg.breached(t0 + h(5))], ["A"])
        self.assertIn("UTC", reg.postmortem("A"))


if __name__ == "__main__":
    unittest.main()
