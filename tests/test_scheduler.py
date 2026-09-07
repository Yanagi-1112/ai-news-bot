from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.config import Settings
from bot.scheduler import JST, NewsScheduler
from bot.store import Store


class EmptyCollector:
    def collect(self, sources):
        return []


class NoopCurator:
    def curate(self, articles):
        return None


class RecordingPoster:
    def __init__(self, store):
        self.store = store
        self.breaking = []
        self.digest = []
    def send_breaking(self, article):
        self.breaking.append(article["id"])
        self.store.update_article(article["id"], state="sent")
        return True
    def send_digest(self, articles, day, breaking):
        self.digest.append([article["id"] for article in articles])
        for article in articles:
            self.store.update_article(article["id"], state="sent")
        return True


def runtime(store, poster, hour=8):
    settings = Settings("x", "stub", "stub", "stub", post_hour_jst=hour, breaking_threshold=90, data_dir=Path("/tmp/newsbot-test-heartbeat"))
    return NewsScheduler(store, EmptyCollector(), NoopCurator(), poster, settings, [])


def add_scored(store, title, score, category="official"):
    article_id = store.add_article({"url": f"https://example.com/{title}", "title": title, "source_id": "s", "source_category": category})
    store.update_article(article_id, state="scored", score=score, headline_ja=title, summary_ja="概要")
    return article_id


def test_breaking_threshold_and_one_per_jst_day():
    store = Store()
    poster = RecordingPoster(store)
    # 空DBの初回判定を避けるため、既読記事を一件置く。
    store.add_article({"url": "https://example.com/old", "title": "old", "source_id": "s", "source_category": "official"}, initial=True)
    first, second = add_scored(store, "major-one", 95), add_scored(store, "major-two", 99)
    scheduler = runtime(store, poster, hour=23)
    scheduler.tick(datetime(2026, 9, 7, 7, 0, tzinfo=JST))
    assert poster.breaking == [first]
    assert store.breaking_count("2026-09-07") == 1
    scheduler.tick(datetime(2026, 9, 7, 7, 30, tzinfo=JST))
    assert poster.breaking == [first]
    scheduler.tick(datetime(2026, 9, 8, 7, 0, tzinfo=JST))
    assert poster.breaking == [first, second]


def test_initial_collection_is_skipped_and_no_digest():
    class OneCollector:
        def collect(self, sources):
            return [{"url": "https://example.com/existing", "title": "既存記事", "source_id": "s", "source_category": "official"}]
    store = Store()
    poster = RecordingPoster(store)
    scheduler = NewsScheduler(store, OneCollector(), NoopCurator(), poster, Settings("x", "stub", "stub", "stub", data_dir=Path("/tmp/newsbot-test-heartbeat")), [])
    assert scheduler.tick(datetime(2026, 9, 7, 9, 0, tzinfo=JST)) == []
    assert store.get_articles()[0]["state"] == "skipped"
    assert not poster.breaking and not poster.digest


def test_no_candidates_does_not_send_digest():
    store = Store()
    poster = RecordingPoster(store)
    store.add_article({"url": "https://example.com/old", "title": "old", "source_id": "s", "source_category": "official"}, initial=True)
    runtime(store, poster).tick(datetime(2026, 9, 7, 8, 0, tzinfo=JST))
    assert poster.digest == []


def test_stale_scored_articles_are_excluded_from_digest():
    """48時間より古い候補はダイジェストに載らず、鮮度切れとしてskippedになる。"""
    store = Store()
    poster = RecordingPoster(store)
    store.add_article({"url": "https://example.com/old", "title": "old", "source_id": "s", "source_category": "official"}, initial=True)
    stale_id = store.add_article({"url": "https://example.com/stale-news", "title": "stale-news",
                                  "source_id": "s", "source_category": "official",
                                  "first_seen_at": "2026-09-04T00:00:00+00:00"})
    store.update_article(stale_id, state="scored", score=80, headline_ja="古い記事", summary_ja="概要")
    fresh_id = store.add_article({"url": "https://example.com/fresh-news", "title": "fresh-news",
                                  "source_id": "s", "source_category": "official",
                                  "first_seen_at": "2026-09-07T00:00:00+00:00"})
    store.update_article(fresh_id, state="scored", score=70, headline_ja="新しい記事", summary_ja="概要")
    runtime(store, poster).tick(datetime(2026, 9, 7, 9, 0, tzinfo=JST))
    assert poster.digest == [[fresh_id]]
    assert store.get_article(stale_id)["state"] == "skipped"
