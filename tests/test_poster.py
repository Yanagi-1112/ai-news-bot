import httpx

from bot.poster import Poster, build_digest
from bot.store import Store


def make_article(store, title="新モデル"):
    article_id = store.add_article({"url": f"https://example.com/item-{len(store.get_articles())}", "title": title, "source_id": "s", "source_category": "official"})
    store.update_article(article_id, state="scored", score=80, headline_ja=title, summary_ja="試せる新しい機能です。")
    return store.get_article(article_id)


def client_with(status=None, error=None, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        if error:
            raise error
        return httpx.Response(status, json={"id": "message-1"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_post_state_transitions_and_timeout_is_not_retried():
    store = Store()
    item = make_article(store)
    poster = Poster(store, "https://discord.example/webhook", client_with(204))
    assert poster.send_breaking(item)
    assert store.get_article(item["id"])["state"] == "sent"

    item2 = make_article(store, "次のモデル")
    poster = Poster(store, "https://discord.example/webhook", client_with(500))
    assert not poster.send_breaking(item2)
    assert store.get_article(item2["id"])["state"] == "scored"

    item3 = make_article(store, "タイムアウトするモデル")
    calls = []
    poster = Poster(store, "https://discord.example/webhook", client_with(error=httpx.ReadTimeout("timeout"), seen=calls))
    assert not poster.send_breaking(item3)
    assert len(calls) == 1
    assert store.get_article(item3["id"])["state"] == "uncertain"
    # uncertainは候補に戻さないので、同じ投稿メソッドを自動再実行しない設計である。


def test_digest_format_mentions_and_length():
    store = Store()
    top = make_article(store, "長い見出し" * 100)
    others = []
    for i in range(4):
        others.append(make_article(store, f"次点 {i}"))
    content = build_digest([top, *others], __import__("datetime").date(2026, 9, 7))
    assert "https://example.com/item-0" in content
    assert "<https://example.com/item-1>" in content
    assert len(content) <= 2000
    seen = []
    poster = Poster(store, "https://discord.example/webhook", client_with(200, seen=seen))
    assert poster.send_digest([top], __import__("datetime").date.today())
    import json
    assert json.loads(seen[0].content)["allowed_mentions"] == {"parse": []}
