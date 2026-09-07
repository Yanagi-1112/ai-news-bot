from types import SimpleNamespace

from bot.config import Settings
from bot.curator import Curator
from bot.store import Store


def test_invalid_llm_json_is_skipped_without_exception():
    store = Store()
    article_id = store.add_article({"url": "https://example.com/a", "title": "モデル", "source_id": "x", "source_category": "official"})
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))
    settings = Settings("x", "https://llm.example", "key", "model")
    curator = Curator(store, settings, client=client)
    curator.curate()
    assert store.get_article(article_id)["state"] == "skipped"


def test_stub_truncates_title_and_summary():
    store = Store()
    article_id = store.add_article({"url": "https://example.com/a", "title": "モデル公開" * 100, "source_id": "x", "source_category": "official"})
    curator = Curator(store, Settings("x", "stub", "stub", "stub"))
    curator.curate()
    article = store.get_article(article_id)
    assert article["state"] == "scored"
    assert len(article["headline_ja"]) <= 300
    assert len(article["summary_ja"]) <= 200
