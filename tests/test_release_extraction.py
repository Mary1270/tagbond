import json
import unittest

from _bootstrap import (
    m, TAG, ASSET, LOGIN, SHA, BASE_EPOCH, DAY, gh_ts, release_json, asset_json, list_json,
)


class TestLenientJson(unittest.TestCase):
    def test_object_array_and_wrapped_pages(self):
        self.assertEqual(m._load_json_lenient('{"a": 1}'), {"a": 1})
        self.assertEqual(m._load_json_lenient('[{"a": 1}]'), [{"a": 1}])
        self.assertEqual(m._load_json_lenient('<pre>{"a": 1}</pre>'), {"a": 1})
        self.assertEqual(m._load_json_lenient('<pre>[{"a": 1}, {"b": 2}]</pre>'), [{"a": 1}, {"b": 2}])

    def test_an_array_wrapper_does_not_return_its_first_inner_object(self):
        self.assertEqual(m._load_json_lenient('xx [{"a": 1}, {"b": 2}] yy'), [{"a": 1}, {"b": 2}])

    def test_garbage_and_empty_are_none(self):
        for bad in ("", None, "not json", "{", "[", "}{", "]["):
            with self.subTest(bad=bad):
                self.assertIsNone(m._load_json_lenient(bad))

    def test_oversized_content_is_cut_and_fails_closed(self):
        self.assertIsNone(m._load_json_lenient("[" + "1," * 2_000_000 + "1]"))


class TestAsset(unittest.TestCase):
    def test_the_named_asset_is_found_by_exact_name(self):
        a = m._extract_asset([asset_json(name="other.zip"), asset_json()], ASSET)
        self.assertEqual(a, {"name": ASSET, "size": 5000, "state": "uploaded", "uploader_login": LOGIN.lower(),
                             "digest": "sha256:" + SHA})

    def test_names_are_case_sensitive(self):
        self.assertIsNone(m._extract_asset([asset_json(name=ASSET.upper())], ASSET))

    def test_missing_asset_and_bad_lists(self):
        for bad in (None, [], {}, "x", [None, 1, "a"], [asset_json(name="x")]):
            with self.subTest(bad=bad):
                self.assertIsNone(m._extract_asset(bad, ASSET))

    def test_volatile_fields_never_reach_the_facts(self):
        a = m._extract_asset([asset_json(download_count=99, updated_at="x", extra={"a": 1})], ASSET)
        self.assertEqual(set(a), {"name", "size", "state", "uploader_login", "digest"})

    def test_sizes_are_validated(self):
        for value, expected in ((0, 0), (5000, 5000), (10 ** 13, 10 ** 13), (10 ** 13 + 1, None), (-1, None),
                                (True, None), (1.5, None), ("5000", None), (None, None)):
            with self.subTest(value=value):
                self.assertEqual(m._extract_asset([asset_json(size=value)], ASSET)["size"], expected)

    def test_digest_state_and_uploader_are_normalised(self):
        a = m._extract_asset([asset_json(digest="SHA256:ABCDEF", state="Uploaded", uploader={"login": "OctoDev"})], ASSET)
        self.assertEqual((a["digest"], a["state"], a["uploader_login"]), ("sha256:abcdef", "uploaded", "octodev"))

    def test_missing_or_malformed_fields_become_empty_not_errors(self):
        a = m._extract_asset([{"name": ASSET}], ASSET)
        self.assertEqual(a, {"name": ASSET, "size": None, "state": "", "uploader_login": "", "digest": ""})
        a = m._extract_asset([asset_json(digest=5, state=7, uploader="x")], ASSET)
        self.assertEqual((a["digest"], a["state"], a["uploader_login"]), ("", "", ""))

    def test_only_a_bounded_number_of_assets_is_scanned(self):
        many = [asset_json(name=f"a{i}.zip") for i in range(m.MAX_ASSETS_SCANNED)] + [asset_json()]
        self.assertIsNone(m._extract_asset(many, ASSET))


class TestRelease(unittest.TestCase):
    def test_facts_of_a_good_release(self):
        facts = m._extract_release(json.dumps(release_json()), TAG, ASSET)
        self.assertEqual(facts["tag"], TAG)
        self.assertEqual(facts["author_login"], LOGIN.lower())
        self.assertEqual(facts["published_at"], BASE_EPOCH + DAY)
        self.assertFalse(facts["draft"])
        self.assertFalse(facts["prerelease"])
        self.assertEqual(facts["asset"]["size"], 5000)

    def test_only_decisive_fields_are_kept(self):
        facts = m._extract_release(json.dumps(release_json()), TAG, ASSET)
        self.assertEqual(set(facts), {"tag", "draft", "prerelease", "published_at", "author_login", "name",
                                      "body_excerpt", "asset"})

    def test_a_release_for_another_tag_is_not_accepted(self):
        self.assertIsNone(m._extract_release(json.dumps(release_json(tag_name="v2.0.0")), TAG, ASSET))
        self.assertIsNone(m._extract_release(json.dumps(release_json(tag_name="V1.0.0")), TAG, ASSET))

    def test_not_a_release(self):
        for bad in ("", "x", "[]", "{}", json.dumps({"message": "Not Found"}), json.dumps(release_json(tag_name=None)),
                    json.dumps(release_json(tag_name=5))):
            with self.subTest(bad=bad):
                self.assertIsNone(m._extract_release(bad, TAG, ASSET))

    def test_timestamps_must_be_strict(self):
        for value in ("2026-03-02", "2026-03-02T12:00:00+00:00", "2026-13-02T12:00:00Z", "yesterday", 5, None):
            with self.subTest(value=value):
                facts = m._extract_release(json.dumps(release_json(published_at=value)), TAG, ASSET)
                self.assertIsNone(facts["published_at"])

    def test_text_is_collapsed_and_bounded(self):
        facts = m._extract_release(json.dumps(release_json(name="a  b\n c", body="x" * 5000)), TAG, ASSET)
        self.assertEqual(facts["name"], "a b c")
        self.assertEqual(len(facts["body_excerpt"]), 1000)

    def test_missing_author_is_empty(self):
        facts = m._extract_release(json.dumps(release_json(author=None)), TAG, ASSET)
        self.assertEqual(facts["author_login"], "")

    def test_booleans_must_be_literal_true(self):
        facts = m._extract_release(json.dumps(release_json(draft="true", prerelease=1)), TAG, ASSET)
        self.assertFalse(facts["draft"])
        self.assertFalse(facts["prerelease"])


class TestList(unittest.TestCase):
    def test_release_found_in_a_short_list(self):
        page = json.dumps(list_json(release_json(tag_name="v0.9.0"), release_json()))
        facts = m._extract_list(page, TAG, ASSET)
        self.assertTrue(facts["complete"])
        self.assertEqual(facts["release"]["tag"], TAG)

    def test_absence_in_a_complete_list(self):
        facts = m._extract_list(json.dumps(list_json(release_json(tag_name="v0.9.0"))), TAG, ASSET)
        self.assertEqual(facts, {"kind": "list", "complete": True, "release": None})
        self.assertEqual(m._extract_list("[]", TAG, ASSET), {"kind": "list", "complete": True, "release": None})

    def test_a_full_page_is_not_complete(self):
        items = [release_json(tag_name=f"v0.{i}.0") for i in range(m.LIST_PER_PAGE)]
        facts = m._extract_list(json.dumps(items), TAG, ASSET)
        self.assertFalse(facts["complete"])
        self.assertIsNone(facts["release"])

    def test_a_full_page_can_still_contain_the_release(self):
        items = [release_json(tag_name=f"v0.{i}.0") for i in range(m.LIST_PER_PAGE - 1)] + [release_json()]
        facts = m._extract_list(json.dumps(items), TAG, ASSET)
        self.assertFalse(facts["complete"])
        self.assertEqual(facts["release"]["tag"], TAG)

    def test_too_many_items_or_malformed_items_are_rejected(self):
        self.assertIsNone(m._extract_list(json.dumps([release_json()] * (m.LIST_PER_PAGE + 1)), TAG, ASSET))
        self.assertIsNone(m._extract_list(json.dumps([release_json(), "x"]), TAG, ASSET))
        self.assertIsNone(m._extract_list(json.dumps([release_json(), None]), TAG, ASSET))

    def test_not_a_list(self):
        for bad in ("", "x", "{}", json.dumps(release_json()), json.dumps({"message": "API rate limit exceeded"})):
            with self.subTest(bad=bad):
                self.assertIsNone(m._extract_list(bad, TAG, ASSET))

    def test_list_facts_carry_no_volatile_count(self):
        facts = m._extract_list(json.dumps(list_json(release_json())), TAG, ASSET)
        self.assertEqual(set(facts), {"kind", "complete", "release"})

    def test_publication_time_is_githubs_not_the_commit_date(self):
        facts = m._extract_list(json.dumps(list_json(release_json(created_at=gh_ts(1), published_at=gh_ts(BASE_EPOCH + 5)))),
                                TAG, ASSET)
        self.assertEqual(facts["release"]["published_at"], BASE_EPOCH + 5)


if __name__ == "__main__":
    unittest.main()
