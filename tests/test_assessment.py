import unittest

from _bootstrap import (
    m, BASE_EPOCH, DAY, DEADLINE_EPOCH, SHA, TAG, LOGIN, MIN_BYTES, gh_ts, anchors, gather, assess, release_url, list_url,
    release_json, late_release_json, no_asset_release_json, asset_json, list_json,
)

D, P, N, U = m.OUT_DELIVERED, m.OUT_PARTIAL, m.OUT_NOT_DELIVERED, m.OUT_UNDETERMINED


def verdict(data, **anchor_over):
    """Verdict group the release lands in, via the full gather/assess path."""
    a = assess({release_url(): data}, anchors(**anchor_over))
    groups = [g for g in ("delivered", "late", "rejected", "failed") if a[g]]
    return groups[0] if groups else "unrelated", a


def hashed(**over):
    return dict(expected_sha256=SHA, **over)


class TestDelivered(unittest.TestCase):
    def test_a_complete_release_in_the_window_is_delivered_but_not_proven_without_a_hash(self):
        v, a = verdict(release_json())
        self.assertEqual(v, "delivered")
        self.assertEqual((a["proven_delivered"], a["proven_late"]), ([], []))
        self.assertEqual(a["delivered"], [TAG])

    def test_with_a_matching_anchored_hash_delivery_is_proven(self):
        v, a = verdict(release_json(), **hashed())
        self.assertEqual((v, a["proven_delivered"]), ("delivered", [TAG]))

    def test_the_window_edges_are_inclusive(self):
        self.assertEqual(verdict(release_json(published_at=gh_ts(BASE_EPOCH)))[0], "delivered")
        self.assertEqual(verdict(release_json(published_at=gh_ts(DEADLINE_EPOCH)))[0], "delivered")
        self.assertEqual(verdict(release_json(published_at=gh_ts(DEADLINE_EPOCH + 1)))[0], "late")
        self.assertEqual(verdict(release_json(published_at=gh_ts(BASE_EPOCH - 1)))[0], "unrelated")

    def test_the_minimum_size_is_inclusive(self):
        self.assertEqual(verdict(release_json(assets=[asset_json(size=MIN_BYTES)]))[0], "delivered")
        self.assertEqual(verdict(release_json(assets=[asset_json(size=MIN_BYTES - 1)]))[0], "rejected")

    def test_digest_case_and_prefix_are_normalised_but_the_value_must_match(self):
        self.assertEqual(verdict(release_json(assets=[asset_json(digest="SHA256:" + SHA.upper())]), **hashed())[1]["proven_delivered"], [TAG])
        for digest in ("sha256:" + "cd" * 32, "md5:" + SHA, SHA, "", None, 5):
            with self.subTest(digest=digest):
                v, a = verdict(release_json(assets=[asset_json(digest=digest)]), **hashed())
                self.assertEqual((v, a["proven_delivered"]), ("rejected", []))

    def test_a_missing_digest_blocks_a_hash_anchored_pact_but_not_an_unhashed_one(self):
        data = release_json(assets=[asset_json(digest=None)])
        self.assertEqual(verdict(data)[0], "delivered")
        self.assertEqual(verdict(data, **hashed())[0], "rejected")


class TestRejectedAndFailed(unittest.TestCase):
    def test_in_time_but_incomplete_is_rejected_never_failed(self):
        cases = {
            "no asset": release_json(assets=[]),
            "another asset": release_json(assets=[asset_json(name="other.zip")]),
            "small asset": release_json(assets=[asset_json(size=1)]),
            "unknown size": release_json(assets=[asset_json(size=None)]),
            "asset not uploaded": release_json(assets=[asset_json(state="starter")]),
            "asset uploaded by someone else": release_json(assets=[asset_json(uploader={"login": "mallory"})]),
            "prerelease": release_json(prerelease=True),
        }
        for name, data in cases.items():
            with self.subTest(name):
                v, a = verdict(data)
                self.assertEqual(v, "rejected")
                self.assertFalse(a["non_delivery_supported"])

    def test_late_and_incomplete_is_failed_and_supports_non_delivery(self):
        for data in (late_release_json(assets=[]), late_release_json(prerelease=True),
                     late_release_json(assets=[asset_json(size=1)])):
            v, a = verdict(data)
            self.assertEqual(v, "failed")
            self.assertTrue(a["non_delivery_supported"])

    def test_late_and_complete_is_late_and_never_non_delivery(self):
        v, a = verdict(late_release_json())
        self.assertEqual(v, "late")
        self.assertFalse(a["non_delivery_supported"])
        self.assertEqual(verdict(late_release_json(), **hashed())[1]["proven_late"], [TAG])


class TestUnrelated(unittest.TestCase):
    def test_other_authors_drafts_and_unpublished_releases_are_ignored(self):
        for data in (release_json(author={"login": "mallory"}), release_json(author=None), release_json(draft=True),
                     release_json(published_at=None), release_json(published_at="soon")):
            with self.subTest(data=data):
                v, a = verdict(data)
                self.assertEqual(v, "unrelated")
                self.assertEqual((a["delivered"], a["late"], a["rejected"], a["failed"]), ([], [], [], []))
                self.assertFalse(a["non_delivery_supported"])

    def test_the_author_match_ignores_case(self):
        self.assertEqual(verdict(release_json(author={"login": LOGIN.upper()}))[0], "delivered")

    def test_a_release_published_before_the_pact_existed_never_counts(self):
        self.assertEqual(verdict(release_json(published_at=gh_ts(BASE_EPOCH - DAY)))[0], "unrelated")

    def test_an_unrelated_release_is_not_a_reason_to_call_non_delivery(self):
        a = assess({release_url(): release_json(author={"login": "mallory"})})
        self.assertFalse(a["non_delivery_supported"])
        self.assertTrue(m._needs_retry(a) is False)


class TestPages(unittest.TestCase):
    def test_the_list_and_the_record_agree_and_do_not_double_count(self):
        a = assess({release_url(): release_json(), list_url(): list_json(release_json())})
        self.assertEqual(a["delivered"], [TAG])
        self.assertEqual(len(a["reports"]), 2)
        self.assertEqual((a["parsed_releases"], a["parsed_lists"]), (1, 1))

    def test_a_complete_list_without_the_tag_proves_absence(self):
        a = assess({list_url(): list_json(release_json(tag_name="v0.9.0"))})
        self.assertTrue(a["absence_proven"])
        self.assertTrue(a["absence_counted"])
        self.assertTrue(a["non_delivery_supported"])

    def test_absence_is_not_counted_before_the_settling_lag(self):
        a = assess({list_url(): list_json()}, anchors(absence_ready=False))
        self.assertTrue(a["absence_proven"])
        self.assertFalse(a["absence_counted"])
        self.assertFalse(a["non_delivery_supported"])
        self.assertTrue(m._needs_retry(a))

    def test_a_full_list_page_without_the_tag_proves_nothing(self):
        items = [release_json(tag_name=f"v0.{i}.0") for i in range(m.LIST_PER_PAGE)]
        a = assess({list_url(): items})
        self.assertFalse(a["absence_proven"])
        self.assertEqual(a["unreadable"], 1)
        self.assertTrue(m._needs_retry(a))

    def test_unreadable_pages_are_counted_not_guessed(self):
        a = assess({release_url(): "<html>rate limited</html>"})
        self.assertEqual((a["unreadable"], a["parsed_releases"]), (1, 0))
        self.assertFalse(a["non_delivery_supported"])
        self.assertTrue(m._needs_retry(a))
        a = assess({release_url(): {"message": "Not Found"}})
        self.assertEqual(a["unreadable"], 1)

    def test_a_404_inside_the_closure_becomes_an_unreadable_page_not_an_exception(self):
        pages = gather({release_url(): None})
        self.assertEqual(pages[0]["release"], None)
        self.assertEqual(pages[0]["content"], m.UNPARSED)

    def test_a_delivery_wins_over_an_unreadable_sibling(self):
        a = assess({release_url(): release_json(), list_url(): "garbage"})
        self.assertEqual(a["delivered"], [TAG])
        self.assertFalse(m._needs_retry(a))

    def test_urls_that_are_not_valid_for_the_pact_are_skipped(self):
        a = assess({"https://api.github.com/repos/evil/x/releases": list_json()})
        self.assertEqual((a["parsed_lists"], a["unreadable"], a["absence_proven"]), (0, 0, False))

    def test_the_assessment_is_plain_json_data(self):
        import json
        a = assess({release_url(): release_json(), list_url(): list_json(release_json())})
        self.assertEqual(json.loads(json.dumps(a)), a)


class TestDecisionTables(unittest.TestCase):
    def a(self, **over):
        base = {"delivered": [], "late": [], "rejected": [], "failed": [], "proven_delivered": [], "proven_late": [],
                "absence_proven": False, "absence_counted": False, "unreadable": 0, "parsed_releases": 1,
                "parsed_lists": 0, "non_delivery_supported": False, "reports": []}
        base.update(over)
        return base

    def test_model_needed(self):
        f = m._model_needed
        self.assertTrue(f(self.a(delivered=[TAG]), False))
        self.assertTrue(f(self.a(delivered=[TAG]), True))
        self.assertFalse(f(self.a(delivered=[TAG], proven_delivered=[TAG]), True))
        self.assertFalse(f(self.a(late=[TAG]), True))
        self.assertTrue(f(self.a(late=[TAG]), False))
        self.assertFalse(f(self.a(late=[TAG], proven_late=[TAG]), False))
        self.assertTrue(f(self.a(non_delivery_supported=True), False))
        self.assertFalse(f(self.a(non_delivery_supported=True), True))
        self.assertFalse(f(self.a(rejected=[TAG]), False))
        self.assertFalse(f(self.a(), False))
        self.assertFalse(f(self.a(delivered=[TAG]), False, model_allowed=False))

    def test_decide(self):
        f = m._decide
        d = self.a(delivered=[TAG])
        self.assertEqual([f(d, c) for c in (D, P, U, N, None)], [D, P, U, U, U])
        self.assertEqual([f(self.a(delivered=[TAG], proven_delivered=[TAG]), c) for c in (D, P, U, N, None)], [D] * 5)
        late = self.a(late=[TAG])
        self.assertEqual([f(late, c) for c in (D, P, U, N, None)], [U, P, U, U, U])
        self.assertEqual([f(self.a(late=[TAG], proven_late=[TAG]), c) for c in (D, P, U, N, None)], [P] * 5)
        nd = self.a(non_delivery_supported=True, failed=[TAG])
        self.assertEqual([f(nd, c) for c in (D, P, U, N, None)], [U, U, U, N, U])
        self.assertEqual([f(self.a(rejected=[TAG]), c) for c in (D, P, U, N, None)], [U] * 5)

    def test_backstop(self):
        self.assertEqual(m._apply_backstop(D, self.a(late=[TAG])), U)
        self.assertEqual(m._apply_backstop(D, self.a(delivered=[TAG])), D)
        self.assertEqual(m._apply_backstop(P, self.a()), P)

    def test_premature_guard(self):
        self.assertEqual(m._premature_guard(N, True), U)
        self.assertEqual(m._premature_guard(P, True), U)
        self.assertEqual(m._premature_guard(D, True), D)
        self.assertEqual(m._premature_guard(N, False), N)

    def test_jury_options(self):
        f = m._jury_options
        self.assertEqual(f(self.a(delivered=[TAG]), False), sorted([D, P, U]))
        self.assertEqual(f(self.a(delivered=[TAG], proven_delivered=[TAG]), False), [D])
        self.assertEqual(f(self.a(late=[TAG]), False), sorted([P, U]))
        self.assertEqual(f(self.a(late=[TAG], proven_late=[TAG]), False), [P])
        self.assertEqual(f(self.a(rejected=[TAG]), False), sorted([N, P, U]))
        self.assertEqual(f(self.a(non_delivery_supported=True), False), sorted([N, U]))
        self.assertEqual(f(self.a(), False), [U])
        self.assertEqual(f(self.a(delivered=[TAG]), True), sorted([D, U]))
        self.assertEqual(f(self.a(delivered=[TAG], proven_delivered=[TAG]), True), [D])
        self.assertEqual(f(self.a(rejected=[TAG]), True), [U])

    def test_a_proven_delivery_cannot_be_appealed_to_anything_else(self):
        a = assess({release_url(): release_json()}, anchors(expected_sha256=SHA))
        self.assertEqual(m._jury_options(a, False), [D])


if __name__ == "__main__":
    unittest.main()
