"""ネットワークを使わず、フェーズBの状態遷移を固定する回帰テスト。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from bot.collector import Collector
from bot.config import Settings
from bot.curator import Curator
from bot.poster import Poster, build_digest
from bot.scheduler import NewsScheduler
from bot.store import Store, normalize_url

JST = ZoneInfo("Asia/Tokyo")


def item(url: str, title: str = "Model Release", category: str = "official") -> dict:
    return {"url": url, "title": title, "source_id": "test", "source_category": category}


def make_settings(tmp_path: Path, *, hour: int = 8) -> Settings:
    return Settings("https://discord.example/hook", "stub", "stub", "stub", hour, 90, tmp_path)


def add_scored(store: Store, url: str, score: int = 80, title: str = "Model Release") -> int:
    article_id = store.add_article(item(url, title))
    assert article_id is not None
    store.update_article(article_id, state="scored", score=score, breaking=int(score >= 90), headline_ja="日本語見出し", summary_ja="短い要約", score_reason="理由")
    return article_id


class EmptyCollector:
    def collect(self, sources: list[dict]) -> list[dict]:
        return []


class NoopCurator:
    def curate(self, articles: list[dict]) -> None:
        return None


def mock_client(status: int = 200, *, timeout: bool = False, captured: list[httpx.Request] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        if timeout:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(status, json={"id": "msg-1"}, request=request)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_url_normalization_and_duplicate_similarity() -> None:
    store = Store()
    assert normalize_url("HTTPS://Example.COM/path/?utm_source=x&x=1#section") == "https://example.com/path?x=1"
    assert store.add_article(item("https://example.com/a?utm_campaign=x", "A long release announcement"))
    assert store.add_article(item("https://example.com/a", "Different title")) is None
    assert store.add_article(item("https://another.example/a", "A long release announcement!")) is None


def test_breaking_threshold_and_daily_limit(tmp_path: Path) -> None:
    store = Store()
    first = add_scored(store, "https://example.com/one", 95)
    second = add_scored(store, "https://example.com/two", 99, "Another Model Release")
    poster = Poster(store, "https://discord.example/hook", mock_client())
    scheduler = NewsScheduler(store, EmptyCollector(), NoopCurator(), poster, make_settings(tmp_path), [])
    scheduler.tick(datetime(2026, 9, 7, 7, tzinfo=JST))
    assert store.breaking_count("2026-09-07") == 1
    assert store.get_article(first)["state"] == "sent"
    assert store.get_article(second)["state"] == "scored"


def test_jst_date_boundary_resets_daily_keys(tmp_path: Path) -> None:
    store = Store()
    store.increment_breaking("2026-09-07")
    store.mark_digest_sent("2026-09-07")
    article_id = add_scored(store, "https://example.com/one", 95)
    poster = Poster(store, "https://discord.example/hook", mock_client())
    scheduler = NewsScheduler(store, EmptyCollector(), NoopCurator(), poster, make_settings(tmp_path), [])
    scheduler.tick(datetime(2026, 9, 8, 0, tzinfo=JST))
    assert store.breaking_count("2026-09-08") == 1
    assert not store.digest_sent("2026-09-08")
    assert store.get_article(article_id)["state"] == "sent"


@pytest.mark.parametrize(("status", "timeout", "expected"), [(200, False, "sent"), (500, False, "scored"), (200, True, "uncertain")])
def test_post_state_transitions(status: int, timeout: bool, expected: str) -> None:
    store = Store()
    article_id = add_scored(store, "https://example.com/one")
    calls: list[httpx.Request] = []
    poster = Poster(store, "https://discord.example/hook", mock_client(status, timeout=timeout, captured=calls))
    assert poster.send_breaking(store.get_article(article_id)) is (expected == "sent")
    assert len(calls) == 1
    assert store.get_article(article_id)["state"] == expected


def test_broken_rss_does_not_stop_other_source() -> None:
    store = Store()
    bad = {"id": "bad", "type": "rss", "url": "https://bad.example/rss", "category": "official"}
    good = {"id": "good", "type": "rss", "url": "https://good.example/rss", "category": "official"}
    def handler(request: httpx.Request) -> httpx.Response:
        content = b"not xml" if "bad" in str(request.url) else b"<rss><channel><item><title>Good Release</title><link>https://good.example/a</link></item></channel></rss>"
        return httpx.Response(200, content=content, request=request)
    collector = Collector(store, httpx.Client(transport=httpx.MockTransport(handler)))
    result = collector.collect([bad, good])
    assert len(result) == 1 and result[0]["title"] == "Good Release"


def test_invalid_llm_json_is_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    article_id = store.add_article(item("https://example.com/a"))
    curator = Curator(store, make_settings(tmp_path))
    monkeypatch.setattr(curator, "_request", lambda batch: (_ for _ in ()).throw(ValueError("bad json")))
    curator.curate([store.get_article(article_id)])
    assert store.get_article(article_id)["state"] == "new"


def test_invalid_llm_schema_retries_only_the_bad_article(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    first = store.add_article(item("https://example.com/a"))
    second = store.add_article(item("https://example.com/b", "Second Release"))
    curator = Curator(store, make_settings(tmp_path))
    valid = {"score": 80, "breaking": False, "headline_ja": "見出し", "summary_ja": "要約", "reason": "理由"}
    monkeypatch.setattr(curator, "_request", lambda batch: [valid, {"score": 101}])
    curator.curate([store.get_article(first), store.get_article(second)])
    assert store.get_article(first)["state"] == "scored"
    assert store.get_article(second)["state"] == "new"


def test_first_collection_marks_existing_as_skipped(tmp_path: Path) -> None:
    store = Store()
    source = {"id": "one", "type": "rss", "url": "https://one.example/rss", "category": "official"}
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"<rss><channel><item><title>Old</title><link>https://one.example/old</link></item></channel></rss>", request=request)))
    scheduler = NewsScheduler(store, Collector(store, client), NoopCurator(), Poster(store, "https://discord.example/hook", mock_client()), make_settings(tmp_path), [source])
    assert scheduler.tick(datetime(2026, 9, 7, 7, tzinfo=JST)) == []
    assert store.get_articles()[0]["state"] == "skipped"


def test_no_digest_for_empty_candidates(tmp_path: Path) -> None:
    store = Store()
    scheduler = NewsScheduler(store, EmptyCollector(), NoopCurator(), Poster(store, "https://discord.example/hook", mock_client()), make_settings(tmp_path), [])
    scheduler.tick(datetime(2026, 9, 7, 9, tzinfo=JST))
    assert not store.digest_sent("2026-09-07")


def test_long_text_and_digest_length_limit() -> None:
    articles = [{"id": index, "title": "T" * 600, "headline_ja": "見出し" * 100, "summary_ja": "要約" * 100, "url": f"https://example.com/{index}"} for index in range(5)]
    output = build_digest(articles, datetime(2026, 9, 7).date())
    assert len(output) <= 2000


def test_digest_format_and_mentions_are_safe() -> None:
    store = Store()
    first, second = add_scored(store, "https://example.com/one"), add_scored(store, "https://example.com/two", title="Second Release")
    captured: list[httpx.Request] = []
    poster = Poster(store, "https://discord.example/hook", mock_client(captured=captured))
    assert poster.send_digest([store.get_article(first), store.get_article(second)], datetime(2026, 9, 7).date())
    payload = captured[0].content.decode()
    assert "https://example.com/one" in payload
    assert "<https://example.com/two>" in payload
    assert '"allowed_mentions":{"parse":[]}' in payload
