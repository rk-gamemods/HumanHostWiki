"""External observations remain bounded, reproducible, and separate from game facts."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.message import Message
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tests._support import fixture_dir

from wikibuild import external_links, mediawiki
from wikibuild.storage import ContractError, digest, json_bytes, writer_lock

PREFIX = "Human Host:Items"
SOURCE = {"api_url": "https://wiki.example/api.php", "namespace": 3000, "namespace_name": "Human Host",
          "prefixes": [PREFIX], "titles": ["Human Host:Biomes"]}
BODY = "== Axe ==\nThis tool repairs damaged structures and harvests wood from trees.\n\nDamage: 10"


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def page(number, leaf, body=BODY, revision=None, redirect=False):
    return {"pageid": number, "title": PREFIX + "/" + leaf, "ns": 3000,
            "lastrevid": revision or number * 10, "length": len(body.encode()), "contentmodel": "wikitext",
            **({"redirect": True} if redirect else {})}, body


class Provider:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []
        self.failure = None

    def __call__(self, parameters):
        self.calls.append(parameters)
        if self.failure:
            raise self.failure
        if "generator" in parameters:
            return {"batchcomplete": True, "query": {"pages": [p for p, body in self.pages]}}
        ids = {int(value) for value in parameters["revids"].split("|")}
        return {"batchcomplete": True, "query": {"pages": [
            {"pageid": p["pageid"], "title": p["title"], "ns": p["ns"], "revisions": [{
                "revid": p["lastrevid"], "slots": {"main": {"contentmodel": p["contentmodel"], "content": body}}}]}
            for p, body in self.pages if p["lastrevid"] in ids]}}


class ExternalLinkTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "external")
        self.source = deepcopy(SOURCE)
        self.now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
        self.provider = Provider(page(1, "Axe"), page(2, "Empty", "== Empty ==\nComing soon."))

    def refresh(self, seconds=0, **kwargs):
        with writer_lock(self.root):
            return external_links.refresh(self.root, self.source, now=self.now + timedelta(seconds=seconds),
                                          request=self.provider, **kwargs)

    def test_round_trip_statuses_and_no_article_bodies_are_retained(self):
        value, result = self.refresh()
        self.assertFalse(result["reused"])
        self.assertEqual(value, external_links.read(self.root, digest(json_bytes(value))))
        self.assertNotIn(BODY, json.dumps(value))
        self.assertEqual(external_links.lookup(value, PREFIX + "/Axe")["status"], "populated")
        self.assertIn("oldid=10", external_links.lookup(value, PREFIX + "/Axe")["url"])
        self.assertEqual(external_links.lookup(value, PREFIX + "/Empty")["status"], "empty")
        missing = external_links.lookup(value, PREFIX + "/Missing")
        self.assertEqual(missing["status"], "missing")
        self.assertNotIn("url", missing)
        self.assertEqual(external_links.lookup(value, "Other Game:Axe")["status"], "unavailable")

    def test_repeat_is_byte_stable_then_expiry_fetches_index_only(self):
        value, _ = self.refresh()
        pointer = self.root / "external-links/latest.json"
        before = pointer.read_bytes(), pointer.stat().st_mtime_ns
        with patch.object(mediawiki, "collect", side_effect=AssertionError("Unexpired observation refetched")):
            second, metrics = self.refresh(1)
        self.assertEqual(value, second)
        self.assertEqual(metrics["requests"], 0)
        self.assertEqual(before, (pointer.read_bytes(), pointer.stat().st_mtime_ns))
        self.provider.calls.clear()
        second, metrics = self.refresh(3600)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(metrics["reused_articles"], 2)
        self.assertNotEqual(value["checked_at"], second["checked_at"])

    def test_changed_revision_and_contract_invalidate_only_the_right_cache(self):
        self.refresh()
        self.provider.calls.clear()
        self.provider.pages[0] = page(1, "Axe", "Damage: 20", revision=11)
        second, metrics = self.refresh(3600)
        self.assertEqual(self.provider.calls[1]["revids"], "11")
        self.assertEqual(metrics["reused_articles"], 1)
        self.assertEqual(external_links.lookup(second, PREFIX + "/Axe")["revision"], 11)
        with patch.object(external_links, "contract", return_value={"new-rule": "a" * 64}):
            _, metrics = self.refresh(3601)
        self.assertEqual(metrics["reused_articles"], 0)

    def test_outage_never_means_missing_and_historical_checks_survive(self):
        value, _ = self.refresh()
        self.provider.failure = OSError("private path and provider detail")
        failed, _ = self.refresh(3600)
        self.assertTrue(failed["retryable"])
        self.assertNotIn("private", json.dumps(failed))
        for leaf in ("Axe", "Missing"):
            self.assertEqual(external_links.lookup(failed, PREFIX + "/" + leaf)["status"], "unavailable")
        self.assertEqual(value, external_links.read(self.root, digest(json_bytes(value))))
        self.assertTrue(self.refresh(3601)[1]["reused"])
        self.provider.failure = None
        recovered, metrics = self.refresh(3660)
        self.assertFalse(metrics["reused"])
        self.assertEqual(metrics["reused_articles"], 2)
        self.assertEqual(external_links.lookup(recovered, PREFIX + "/Axe")["status"], "populated")

    def test_partial_inventory_keeps_positive_checks_but_never_infers_missing(self):
        original = self.provider
        calls = 0

        def interrupted(parameters):
            nonlocal calls
            if "generator" in parameters:
                calls += 1
                if calls == 2:
                    raise mediawiki.RemoteError("failed")
                return {**original(parameters), "continue": {"continue": "gapcontinue||", "gapcontinue": "Later"}}
            return original(parameters)

        self.provider = interrupted
        value, _ = self.refresh()
        self.assertEqual(external_links.lookup(value, PREFIX + "/Axe")["status"], "populated")
        self.assertEqual(external_links.lookup(value, PREFIX + "/Missing")["status"], "unavailable")
        self.assertEqual(external_links.Matcher(value).entity("Axe", [PREFIX])["reason"], "incomplete-index")

    def test_offline_matching_is_exact_scoped_and_ambiguity_is_not_guessed(self):
        self.source["prefixes"].append("Human Host:Weapons")
        other, body = page(3, "Axe")
        other["title"] = "Human Host:Weapons/Axe"
        self.provider.pages.append((other, body))
        value, _ = self.refresh()
        with patch.object(mediawiki, "Client", side_effect=AssertionError("Offline match contacted provider")):
            matcher = external_links.Matcher(value)
            self.assertEqual(matcher.entity("AXE", [PREFIX])["status"], "populated")
            self.assertEqual(matcher.entity("Axes", [PREFIX])["status"], "missing")
            ambiguous = matcher.entity("Axe", self.source["prefixes"])
            self.assertEqual(ambiguous["reason"], "ambiguous-title")
            self.assertNotIn("url", ambiguous)
        with self.assertRaises(ContractError):
            matcher.entity("Axe", ["Human Host:Unobserved"])

    def test_redirect_target_is_checked_again_when_only_destination_changes(self):
        self.provider.pages.append(page(3, "Alias", "#REDIRECT [[Human Host:Items/Axe]]", redirect=True))
        first, _ = self.refresh()
        link = external_links.lookup(first, PREFIX + "/Alias")
        self.assertEqual(link["status"], "populated")
        self.assertEqual(link["destination_revision"], 10)
        self.provider.pages[0] = page(1, "Axe", "", revision=11)
        second, metrics = self.refresh(3600)
        self.assertEqual(metrics["reused_articles"], 2)
        self.assertEqual(external_links.lookup(second, PREFIX + "/Alias")["status"], "empty")
        self.assertNotIn("url", external_links.lookup(second, PREFIX + "/Alias"))

    def test_redirect_cycles_and_unobserved_destinations_do_not_produce_links(self):
        self.provider = Provider(page(1, "A", "#REDIRECT [[Human Host:Items/B]]", redirect=True),
            page(2, "B", "#REDIRECT [[Human Host:Items/A]]", redirect=True),
            page(3, "C", "#REDIRECT [[Other Game:C]]", redirect=True))
        value, _ = self.refresh()
        for leaf in ("A", "B", "C"):
            self.assertEqual(external_links.lookup(value, PREFIX + "/" + leaf)["status"], "unavailable")

    def test_mutated_receipt_and_failed_pointer_promotion_preserve_state(self):
        value, _ = self.refresh()
        old = (self.root / "external-links/latest.json").read_bytes()
        original = external_links.write_changed

        def fail_pointer(path, data):
            if path.name == "latest.json":
                raise OSError("injected promotion failure")
            return original(path, data)

        with patch.object(external_links, "write_changed", side_effect=fail_pointer):
            with self.assertRaises(OSError):
                self.refresh(3600)
        self.assertEqual(old, (self.root / "external-links/latest.json").read_bytes())
        self.assertEqual(value, external_links.latest(self.root))
        self.refresh(3600)
        receipt = self.root / "external-links" / (digest(json_bytes(value)) + ".json")
        receipt.write_bytes(json_bytes({**value, "checked_at": "modified"}))
        with self.assertRaises(ContractError):
            external_links.read(self.root, digest(json_bytes(value)))

    def test_clock_rollback_and_source_changes_cannot_reuse_old_observation(self):
        self.refresh()
        self.assertFalse(self.refresh(-1)[1]["reused"])
        self.source["titles"].append("Human Host:New Topic")
        self.assertFalse(self.refresh()[1]["reused"])

    def test_source_mutation_during_fetch_cannot_promote_an_observation(self):
        provider = self.provider

        def mutate_source(parameters):
            self.source["api_url"] = "https://another.example/api.php"
            return provider(parameters)

        self.provider = mutate_source
        with self.assertRaisesRegex(ContractError, "changed during observation"):
            self.refresh()
        self.assertIsNone(external_links.latest(self.root))


class ProviderTests(unittest.TestCase):
    def test_mediawiki_reads_exhaust_elapsed_budget(self):
        clock = Clock()

        class Slow(io.BytesIO):
            def read1(self, size):
                clock.sleep(1)
                return b"x"

        response = Slow()
        response.url = "https://example.invalid/file"
        response.status = 200
        response.headers = Message()
        response.headers["Content-Type"] = "application/json"
        client = mediawiki.Client("https://example.invalid/api.php", clock=clock)
        with patch.object(client.opener, "open", return_value=response) as opened:
            with self.assertRaisesRegex(mediawiki.RemoteError, "deadline"):
                client({}, deadline=3)
        self.assertEqual(opened.call_args.kwargs["timeout"], 3)
        self.assertEqual(clock.now, 3)
        self.assertTrue(response.closed)

    def test_exhausted_mediawiki_budget_prevents_a_new_request(self):
        clock = Clock()
        client = mediawiki.Client("https://example.invalid/api.php", deadline=0, clock=clock)
        with patch.object(client.opener, "open") as opened:
            with self.assertRaisesRegex(mediawiki.RemoteError, "deadline"):
                client({})
        opened.assert_not_called()

    def test_pagination_and_revision_batches_complete_independently(self):
        provider = Provider(*(page(n, "Item" + str(n)) for n in range(1, 12)))

        def paginated(parameters):
            result = provider(parameters)
            if "generator" in parameters:
                if "gapcontinue" not in parameters:
                    result["query"]["pages"] = result["query"]["pages"][:5]
                    result["continue"] = {"continue": "gapcontinue||", "gapcontinue": "Next"}
                else:
                    result["query"]["pages"] = result["query"]["pages"][5:]
            elif len(parameters["revids"].split("|")) == 10:
                raise mediawiki.RemoteError("one revision batch failed")
            return result

        value, metrics = mediawiki.collect(SOURCE, request=paginated)
        self.assertTrue(value["inventory_complete"])
        self.assertEqual(value["inventory_count"], 11)
        self.assertEqual(sum(check["status"] == "populated" for check in value["pages"].values()), 1)
        self.assertEqual(sum(check["status"] == "unavailable" for check in value["pages"].values()), 10)
        self.assertEqual(metrics["errors"], ["revision-batch-unavailable"])

    def test_repeated_continuation_and_inventory_budget_do_not_claim_completeness(self):
        response = {"batchcomplete": True, "continue": {"continue": "gapcontinue||", "gapcontinue": "Same"}}
        client = Mock(return_value=response)
        value, _ = mediawiki.collect(SOURCE, request=client)
        self.assertFalse(value["inventory_complete"])
        self.assertEqual(client.call_count, 2)
        provider = Provider(page(1, "Axe"), page(2, "Hammer"))
        with patch.object(mediawiki, "MAX_PAGES", 1):
            value, _ = mediawiki.collect(SOURCE, request=provider)
        self.assertFalse(value["inventory_complete"])
        self.assertEqual(len(value["pages"]), 1)

    def test_unsupported_markup_is_reused_until_its_revision_changes(self):
        provider = Provider(page(1, "Template", "{{Info|damage=10}}"))
        value, _ = mediawiki.collect(SOURCE, request=provider)
        provider.calls.clear()
        second, metrics = mediawiki.collect(SOURCE, value["pages"], request=provider)
        self.assertEqual(value, second)
        self.assertEqual(metrics["reused_articles"], 1)
        self.assertEqual(len(provider.calls), 1)

    def test_content_rule_does_not_mistake_navigation_or_templates_for_articles(self):
        cases = [(BODY, "populated"), ("Damage: 10", "populated"),
            ("{| class=wikitable\n| Axe || 10\n|}", "populated"),
            ("== Stats ==\n[[File:Stats.png]]\nReturn To: [[Human Host:Main Page]]", "empty"),
            ("# [[Human Host:Some Guide|A guide with a very long descriptive title]]", "empty"),
            ("This page is under construction and more information will be added soon.", "empty"),
            ("{{Infobox|damage=10}}", "unavailable"), ("<div hidden>" + BODY + "</div>", "unavailable"),
            ("<!--" + BODY, "unavailable"), ("<!--" + BODY + "-->", "empty")]
        for content, expected in cases:
            with self.subTest(content=content):
                self.assertEqual(mediawiki.article_state(content)[0], expected)

    def test_reviewed_formatting_preserves_body_and_navigation_checks(self):
        cases = [
            ("<u>Damage</u>: 10", "populated"),
            ("<code>" + BODY + "</code>", "populated"),
            ("<U><code>Damage</code></U>: 10", "populated"),
            ("== Heading ==<br />Damage: 10", "populated"),
            ("<u>[[Human Host:Some Guide|A guide with a very long descriptive title]]</u>", "empty"),
            ("<code></code><br><u></u>", "empty"),
            ("<u>Coming soon</u><br />", "empty"),
            ("<code>{{Info|damage=10}}</code>", "unavailable"),
            ("<u hidden>" + BODY + "</u>", "unavailable"),
            ("<br onclick='run()'>" + BODY, "unavailable"),
            ("<code>" + BODY, "unavailable"),
            ("<u><code>" + BODY + "</u></code>", "unavailable"),
            ("</code>" + BODY, "unavailable"),
            ("<code" + BODY, "unavailable"),
            ("<!DOCTYPE html>" + BODY, "unavailable"),
        ]
        for content, expected in cases:
            with self.subTest(content=content):
                self.assertEqual(mediawiki.article_state(content)[0], expected)

    def test_incomplete_duplicate_or_wrong_namespace_indexes_never_prove_absence(self):
        entry, body = page(1, "Axe")
        for response in [None, {}, {"query": None}, {"query": {"pages": None}},
            {"query": {"pages": [{**entry, "ns": 0}]}}, {"query": {"pages": [entry, entry]}},
            {"batchcomplete": True, "continue": {"gapcontinue": "A", "other": "injected"}}]:
            with self.subTest(response=response):
                result, _ = mediawiki.collect(SOURCE, request=Mock(return_value=response))
                self.assertFalse(result["inventory_complete"])

    def test_known_oversize_and_unselected_articles_are_not_fetched(self):
        huge = page(2, "Huge", "x" * (mediawiki.MAX_ARTICLE + 1))
        unrelated, body = page(3, "Other")
        unrelated["title"] = "Human Host:Other"
        provider = Provider(page(1, "Axe"), huge, (unrelated, body))
        value, _ = mediawiki.collect(SOURCE, request=provider)
        self.assertEqual(provider.calls[1]["revids"], "10")
        self.assertEqual(value["pages"][PREFIX + "/Huge"]["reason"], "article-budget-exceeded")
        self.assertNotIn("Human Host:Other", value["pages"])

    def test_missing_or_mismatched_revision_does_not_poison_supported_siblings(self):
        provider = Provider(page(1, "Axe"), page(2, "Hammer"))

        def changed(parameters):
            result = provider(parameters)
            if "revids" in parameters:
                result["query"]["pages"][0]["title"] = PREFIX + "/Wrong"
            return result

        result, _ = mediawiki.collect(SOURCE, request=changed)
        self.assertEqual(result["pages"][PREFIX + "/Axe"]["status"], "unavailable")
        self.assertEqual(result["pages"][PREFIX + "/Hammer"]["status"], "populated")

    def test_network_response_bounds_http_shape_and_query_identity(self):
        for raw, content_type, status in [(b"x" * (mediawiki.MAX_RESPONSE + 1), "application/json", 200),
                (b"{}", "text/html", 200), (b"{}", "application/json", 503),
                (b'{"error": {"code": "maxlag"}}', "application/json", 200),
                (b'{"warnings": {}}', "application/json", 200), (b"not json", "application/json", 200)]:
            headers = Message()
            headers["Content-Type"] = content_type
            response = io.BytesIO(raw)
            response.status, response.headers = status, headers
            client = mediawiki.Client(SOURCE["api_url"])
            client.opener = Mock(open=Mock(return_value=response))
            with self.subTest(status=status, content_type=content_type, bytes=len(raw)):
                with self.assertRaises(mediawiki.RemoteError):
                    client({"prop": "info", "action": "edit"})
                request = client.opener.open.call_args.args[0]
                self.assertEqual(request.get_method(), "GET")
                self.assertIn("action=query", request.full_url)
                self.assertIn("maxlag=5", request.full_url)
                self.assertEqual(request.get_header("User-agent"), mediawiki.USER_AGENT)

    def test_redirect_and_exhausted_network_budget_fail_before_more_requests(self):
        with self.assertRaises(mediawiki.RemoteError):
            mediawiki.NoRedirect().redirect_request(None, None, 302, "", {}, "http://elsewhere")
        for field, limit in (("requests", mediawiki.MAX_REQUESTS), ("bytes", mediawiki.MAX_TRANSFER)):
            client = mediawiki.Client(SOURCE["api_url"])
            setattr(client, field, limit)
            client.opener = Mock()
            with self.assertRaises(mediawiki.RemoteError):
                client({})
            client.opener.open.assert_not_called()

    def test_invalid_configuration_is_an_execution_error_before_network_access(self):
        for changes in [{"api_url": "http://wiki.example/api.php"}, {"api_url": "https://user@wiki.example/api.php"},
                {"api_url": "https://[wiki.example/api.php"}, {"api_url": "https://wiki.example:bad/api.php"},
                {"api_url": "https://@wiki.example/api.php"}, {"api_url": "https://wiki.example/api.php\n"},
                {"api_url": "https://wiki.example/api.php?token=secret"}, {"namespace": True},
                {"prefixes": [[]]}, {"titles": ["Human Host:"]}, {"titles": ["Other Game:Axe"]},
                {"titles": ["Human Host:A#section"]}]:
            with self.subTest(changes=changes):
                with patch.object(mediawiki, "Client", side_effect=AssertionError("Network before validation")):
                    with self.assertRaises(ContractError):
                        mediawiki.collect({**SOURCE, **changes})


if __name__ == "__main__":
    unittest.main()
