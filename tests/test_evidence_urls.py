import unittest

from _bootstrap import (
    m, gl, CLOCK, PARTY_A_ADDRESS, PARTY_B_ADDRESS, STRANGER_ADDRESS, REPO, TAG, anchors, release_url, list_url,
    make_contract, set_caller, active_pact, get, expect_user_error,
)


def item(url, **over):
    return m._evidence_item(url, anchors(**over))


class TestEvidenceItem(unittest.TestCase):
    def test_the_two_accepted_shapes(self):
        self.assertEqual(item(release_url()), (release_url(), "release", TAG))
        self.assertEqual(item(list_url()), (list_url(), "list", "list"))

    def test_the_list_without_a_query_or_with_any_page_size_collapses_to_one_form(self):
        base = "https://api.github.com/repos/acme/widgets/releases"
        for url in (base, base + "?per_page=100", base + "?per_page=30", base + "?per_page=1"):
            with self.subTest(url=url):
                self.assertEqual(item(url), (list_url(), "list", "list"))

    def test_repository_case_is_ignored_but_the_anchored_spelling_is_used(self):
        got = item("https://api.github.com/repos/ACME/Widgets/releases/tags/v1.0.0")
        self.assertEqual(got, (release_url(), "release", TAG))

    def test_the_tag_is_case_sensitive(self):
        self.assertIsNone(item("https://api.github.com/repos/acme/widgets/releases/tags/V1.0.0"))

    def test_another_tag_or_repository_is_rejected(self):
        for url in (
            "https://api.github.com/repos/acme/widgets/releases/tags/v2.0.0",
            "https://api.github.com/repos/acme/other/releases/tags/v1.0.0",
            "https://api.github.com/repos/evil/widgets/releases/tags/v1.0.0",
            "https://api.github.com/repos/evil/widgets/releases",
        ):
            with self.subTest(url=url):
                self.assertIsNone(item(url))

    def test_hosts_schemes_and_authority_tricks_are_rejected(self):
        for url in (
            "http://api.github.com/repos/acme/widgets/releases/tags/v1.0.0",
            "https://github.com/repos/acme/widgets/releases/tags/v1.0.0",
            "https://api.github.com.evil.test/repos/acme/widgets/releases/tags/v1.0.0",
            "https://evil.test/api.github.com/repos/acme/widgets/releases/tags/v1.0.0",
            "https://api.github.com:443/repos/acme/widgets/releases/tags/v1.0.0",
            "https://api.github.com:8443/repos/acme/widgets/releases/tags/v1.0.0",
            "https://user@api.github.com/repos/acme/widgets/releases/tags/v1.0.0",
            "https://api.github.com@evil.test/repos/acme/widgets/releases/tags/v1.0.0",
            "https://api.github.com:443@evil.test/repos/acme/widgets/releases/tags/v1.0.0",
            "https://raw.githubusercontent.com/acme/widgets/main/x",
            "ftp://api.github.com/repos/acme/widgets/releases/tags/v1.0.0",
            "api.github.com/repos/acme/widgets/releases/tags/v1.0.0",
            "",
        ):
            with self.subTest(url=url):
                self.assertIsNone(item(url))

    def test_extra_path_query_or_fragment_is_rejected(self):
        for url in (
            release_url() + "?x=1",
            release_url() + "#frag",
            release_url() + "/",
            release_url() + "/assets",
            list_url() + "#frag",
            "https://api.github.com/repos/acme/widgets/releases/",
            "https://api.github.com/repos/acme/widgets/releases?per_page=0",
            "https://api.github.com/repos/acme/widgets/releases?per_page=101",
            "https://api.github.com/repos/acme/widgets/releases?per_page=abc",
            "https://api.github.com/repos/acme/widgets/releases?per_page=5&page=2",
            "https://api.github.com/repos/acme/widgets/releases?page=2",
            "https://api.github.com/repos/acme/widgets/releases?per_page=5&per_page=6",
            "https://api.github.com/repos/acme/widgets/releases/latest",
            "https://api.github.com/repos/acme/widgets/releases/123",
            "https://api.github.com/repos/acme/widgets/pulls/7",
            "https://api.github.com/search/issues?q=repo:acme/widgets",
            "https://api.github.com/repos/acme/widgets/releases/tags/",
            "https://api.github.com/repos/acme/widgets/releases/tags/v1.0.0/../v2",
            "https://api.github.com/repos/acme/widgets/releases/tags/v1.0.0%2f..",
        ):
            with self.subTest(url=url):
                self.assertIsNone(item(url))

    def test_non_strings_do_not_crash(self):
        for bad in (None, 5, [], {}):
            self.assertIsNone(m._evidence_item(bad, anchors()))


class TestSubmitEvidence(unittest.TestCase):
    def setUp(self):
        self.c = make_contract()
        self.bid = active_pact(self.c)

    def submit(self, urls, who=PARTY_B_ADDRESS):
        set_caller(who)
        return self.c.submit_evidence(self.bid, urls)

    def test_items_are_stored_in_canonical_form_and_deduplicated(self):
        self.submit([release_url(), "https://api.github.com/repos/ACME/WIDGETS/releases/tags/v1.0.0",
                     "https://api.github.com/repos/acme/widgets/releases?per_page=30", list_url()])
        stored = get(self.c, self.bid)["evidence_submissions"][PARTY_B_ADDRESS.lower()]
        self.assertEqual(stored, sorted([release_url(), list_url()]))

    def test_one_bad_item_rejects_the_whole_submission(self):
        with self.assertRaises(gl.vm.UserError) as ctx:
            self.submit([release_url(), "https://api.github.com/repos/acme/widgets/releases/tags/v9"])
        self.assertIn("Evidence URL not allowed", str(ctx.exception))
        self.assertEqual(get(self.c, self.bid)["evidence_submissions"], {})

    def test_empty_and_oversized_submissions(self):
        for bad in ([], [""], ["   "], "x", None, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(gl.vm.UserError):
                    self.submit(bad)
        with self.assertRaises(gl.vm.UserError):
            self.submit([release_url() + "?" + "a" * 400])

    def test_only_parties_may_submit(self):
        with self.assertRaises(gl.vm.UserError):
            self.submit([release_url()], who=STRANGER_ADDRESS)

    def test_a_party_can_revise_a_limited_number_of_times(self):
        for _ in range(3):
            self.submit([release_url()])
        with self.assertRaises(gl.vm.UserError):
            self.submit([release_url()])

    def test_both_parties_submitting_locks_the_snapshot(self):
        self.submit([release_url()], who=PARTY_B_ADDRESS)
        self.assertEqual(get(self.c, self.bid)["status"], "active")
        self.submit([list_url()], who=PARTY_A_ADDRESS)
        b = get(self.c, self.bid)
        self.assertEqual(b["status"], "evidence_locked")
        self.assertEqual(b["evidence_snapshot"]["source_urls"], sorted([release_url(), list_url()]))
        self.assertEqual(b["evidence_snapshot"]["accepted_source_count"], 2)

    def test_the_counterparty_has_a_grace_period_then_anyone_can_lock(self):
        self.submit([release_url()])
        set_caller(STRANGER_ADDRESS)
        expect_user_error(self, self.c.lock_evidence, self.bid)
        import datetime
        CLOCK.set(datetime.datetime.fromisoformat(get(self.c, self.bid)["evidence_lock_at"]) + datetime.timedelta(seconds=1))
        self.c.lock_evidence(self.bid)
        self.assertEqual(get(self.c, self.bid)["status"], "evidence_locked")


if __name__ == "__main__":
    unittest.main()
