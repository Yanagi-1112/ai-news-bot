from bot.store import Store, normalize_url


def article(url="https://example.com/a", title="A useful model"):
    return {"url": url, "title": title, "source_id": "official", "source_category": "official"}


def test_normalize_url_and_deduplicate_similar_title():
    store = Store()
    assert normalize_url("HTTPS://Example.COM/a/?utm_source=x&x=1#part") == "https://example.com/a?x=1"
    assert store.add_article(article("https://example.com/a/?utm_medium=test", "A useful model")) is not None
    assert store.add_article(article("https://example.com/a", "A useful model updated")) is None
    assert store.add_article(article("https://other.example/a", "A useful model!")) is None


def test_daily_meta_is_separate_at_jst_boundary():
    store = Store()
    store.increment_breaking("2026-09-07")
    store.mark_digest_sent("2026-09-07")
    assert store.breaking_count("2026-09-07") == 1
    assert store.digest_sent("2026-09-07")
    # 日付が0:00で変われば、新しいmeta keyなので枠もフラグも自動的に新規となる。
    assert store.breaking_count("2026-09-08") == 0
    assert not store.digest_sent("2026-09-08")
