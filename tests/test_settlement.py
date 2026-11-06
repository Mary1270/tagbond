import datetime
import unittest

from _bootstrap import (
    late_release_json, no_asset_release_json,
    m, gl, CLOCK, DAY, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS, REPO, TAG, REWARD, BOND,
    make_contract, set_caller, create_pact, accept_pact, locked_pact, ruled_pact, get, pending, pass_deadline,
    pass_appeal_window, adjudicate, MODEL_PARTIAL, release_json, release_url,
)

D, P, N, U = m.OUT_DELIVERED, m.OUT_PARTIAL, m.OUT_NOT_DELIVERED, m.OUT_UNDETERMINED
CLOSED = dict(merged=False, merged_at=None, state="closed")

SCENARIOS = {
    D: ({release_url(): release_json()}, {"outcome": D}),
    P: ({release_url(): late_release_json()}, {"outcome": P}),
    N: ({release_url(): late_release_json(assets=[])}, {"outcome": N}),
    U: ({release_url(): no_asset_release_json()}, None),
}


def ruling(c, outcome, **over):
    pages, mdl = SCENARIOS[outcome]
    bid = ruled_pact(c, pages=pages, model=mdl, **over)
    assert get(c, bid)["tier1_outcome"] == outcome, get(c, bid)["tier1_outcome"]
    return bid


def settle(c, bid):
    pass_appeal_window(c, bid)
    set_caller(STRANGER_ADDRESS)
    c.settle_unappealed(bid)
    return get(c, bid)


class TestPayouts(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_delivered_pays_the_publisher_the_whole_pot(self):
        bid = ruling(self.c, D)
        b = settle(self.c, bid)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), REWARD + BOND)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), 0)
        self.assertEqual((b["publisher_payout"], b["client_payout"]), (str(REWARD + BOND), "0"))

    def test_not_delivered_pays_the_client_the_whole_pot(self):
        bid = ruling(self.c, N)
        settle(self.c, bid)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), REWARD + BOND)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), 0)

    def test_partial_returns_the_bond_and_splits_the_reward(self):
        bid = ruling(self.c, P)
        settle(self.c, bid)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), BOND + REWARD // 2)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), REWARD - REWARD // 2)

    def test_partial_follows_the_anchored_ratio(self):
        bid = ruling(self.c, P, partial_bps=7000)
        settle(self.c, bid)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), BOND + 7000)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), 3000)

    def test_partial_rounding_favours_the_client_and_loses_nothing(self):
        bid = ruling(self.c, P, reward=10001, partial_bps=3333)
        b = get(self.c, bid)
        settle(self.c, bid)
        share = 10001 * 3333 // 10000
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), int(b["bond_amount"]) + share)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), 10001 - share)

    def test_undetermined_refunds_each_side_its_own_deposit(self):
        bid = ruling(self.c, U)
        settle(self.c, bid)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), REWARD)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), BOND)

    def test_unequal_stakes_follow_bond_bps(self):
        bid = ruling(self.c, U, bond_bps=500)
        settle(self.c, bid)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), REWARD * 500 // 10000)

    def test_money_is_conserved_for_every_outcome_and_parameter_mix(self):
        for outcome in (D, P, N, U):
            for reward, bond_bps, partial in ((10000, 2000, 5000), (10001, 777, 1), (9999, 10000, 9999), (123457, 500, 4321)):
                with self.subTest(outcome=outcome, reward=reward, bond_bps=bond_bps, partial=partial):
                    c = make_contract()
                    bid = ruling(c, outcome, reward=reward, bond_bps=bond_bps, partial_bps=partial)
                    b = settle(c, bid)
                    total = pending(c, PARTY_A_ADDRESS) + pending(c, PARTY_B_ADDRESS)
                    self.assertEqual(total, reward + int(b["bond_amount"]))
                    self.assertEqual(total, int(c.balance))
                    self.assertEqual(int(b["publisher_payout"]) + int(b["client_payout"]), total)

    def test_settlement_stamps_the_time_and_the_final_outcome(self):
        bid = ruling(self.c, D)
        b = settle(self.c, bid)
        self.assertEqual((b["status"], b["final_outcome"], b["payout_settled"]), ("settled", D, True))
        self.assertEqual(b["settled_at"], CLOCK.now.isoformat())


class TestSettleUnappealed(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.bid = ruling(self.c, D)

    def test_cannot_settle_inside_the_appeal_window(self):
        with self.assertRaises(gl.vm.UserError):
            self.c.settle_unappealed(self.bid)

    def test_cannot_settle_exactly_at_the_end_of_the_window(self):
        CLOCK.set(datetime.datetime.fromisoformat(get(self.c, self.bid)["appeal_deadline"]))
        with self.assertRaises(gl.vm.UserError):
            self.c.settle_unappealed(self.bid)

    def test_anyone_can_settle_after_the_window(self):
        pass_appeal_window(self.c, self.bid)
        set_caller(STRANGER_ADDRESS)
        self.c.settle_unappealed(self.bid)
        self.assertEqual(get(self.c, self.bid)["status"], "settled")

    def test_settling_twice_is_rejected_and_never_pays_twice(self):
        settle(self.c, self.bid)
        with self.assertRaises(gl.vm.UserError):
            self.c.settle_unappealed(self.bid)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), REWARD + BOND)

    def test_wrong_status_is_rejected(self):
        CLOCK.reset()
        posted = create_pact(self.c, deadline=CLOCK.now + datetime.timedelta(days=3))
        for bid in (posted, "pact_99"):
            with self.assertRaises(gl.vm.UserError):
                self.c.settle_unappealed(bid)

    def test_payout_flag_guards_the_settlement_function_itself(self):
        b = get(self.c, self.bid)
        b["final_outcome"] = D
        self.c._settle(b)
        self.c._settle(b)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), REWARD + BOND)

    def test_claims_survive_delivered_and_partial_but_not_other_outcomes(self):
        for outcome, kept in ((D, True), (P, True), (N, False), (U, False)):
            with self.subTest(outcome=outcome):
                c = make_contract()
                bid = ruling(c, outcome)
                settle(c, bid)
                self.assertEqual(c.get_release_claim(REPO, TAG), bid if kept else "")

    def test_stats_follow_settlement_and_cancellation(self):
        import json
        self.assertEqual(json.loads(self.c.get_stats()), {"total": 1, "settled": 0, "cancelled": 0, "active": 1})
        settle(self.c, self.bid)
        cancelled = create_pact(self.c, deadline=CLOCK.now + datetime.timedelta(days=5))
        set_caller(PARTY_A_ADDRESS)
        self.c.cancel_pact(cancelled)
        self.assertEqual(json.loads(self.c.get_stats()), {"total": 2, "settled": 1, "cancelled": 1, "active": 0})


class TestRecoveryPaths(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()

    def test_expire_unruled_refunds_both_after_the_timeout(self):
        bid = locked_pact(self.c, urls=[release_url()])
        pass_deadline(self.c, bid)
        set_caller(STRANGER_ADDRESS)
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_unruled(bid)
        b = get(self.c, bid)
        locked_at = datetime.datetime.fromisoformat(b["evidence_snapshot"]["locked_at"])
        base = max(locked_at, datetime.datetime.fromisoformat(b["deadline"]))
        CLOCK.set(base + datetime.timedelta(days=7, seconds=1))
        self.c.expire_unruled(bid)
        self.assertEqual(get(self.c, bid)["final_outcome"], U)
        self.assertEqual(pending(self.c, PARTY_A_ADDRESS), REWARD)
        self.assertEqual(pending(self.c, PARTY_B_ADDRESS), BOND)

    def test_expire_unruled_is_rejected_at_the_exact_timeout_boundary(self):
        bid = locked_pact(self.c, urls=[release_url()])
        b = get(self.c, bid)
        locked_at = datetime.datetime.fromisoformat(b["evidence_snapshot"]["locked_at"])
        base = max(locked_at, datetime.datetime.fromisoformat(b["deadline"]))
        CLOCK.set(base + datetime.timedelta(days=7))
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_unruled(bid)

    def test_expire_unruled_is_only_for_evidence_locked_pacts(self):
        bid = ruling(self.c, D)
        CLOCK.advance(30 * DAY)
        with self.assertRaises(gl.vm.UserError):
            self.c.expire_unruled(bid)

    def test_a_pact_that_cannot_be_ruled_early_can_still_be_ruled_after_the_deadline(self):
        bid = locked_pact(self.c, urls=[release_url()], both=True)
        with self.assertRaises(gl.vm.UserError):
            adjudicate(self.c, bid, {release_url(): late_release_json()}, model=MODEL_PARTIAL)
        pass_deadline(self.c, bid)
        self.assertEqual(adjudicate(self.c, bid, {release_url(): late_release_json()}, model=MODEL_PARTIAL)["tier1_outcome"], P)


if __name__ == "__main__":
    unittest.main()
