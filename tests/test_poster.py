import httpx
from datetime import datetime, timezone

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


def test_payload_includes_display_name_and_avatar():
    """表示名とアイコンURLを指定した場合、全投稿のpayloadに含まれる。"""
    import json as _json
    from bot.store import Store as _Store

    seen = []

    def handler(request):
        seen.append(_json.loads(request.content))
        return httpx.Response(200, json={"id": "m1"})

    store = _Store()
    article_id = store.add_article({"url": "https://example.com/x", "title": "x",
                                    "source_id": "s", "source_category": "official"})
    store.update_article(article_id, state="scored", score=95, headline_ja="見出し", summary_ja="概要")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    poster = Poster(store, "https://discord.example/webhook", client,
                    username="未来に先回りする新聞", avatar_url="https://example.com/icon.png")
    assert poster.send_breaking(store.get_article(article_id))
    assert poster.send_test()
    for payload in seen:
        assert payload["username"] == "未来に先回りする新聞"
        assert payload["avatar_url"] == "https://example.com/icon.png"
        assert payload["allowed_mentions"] == {"parse": []}


def test_fanout_sends_identical_payload_and_records_all_message_ids():
    import json

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": f"message-{len(seen)}"})

    store = Store()
    item = make_article(store)
    poster = Poster(
        store,
        ["https://discord.example/first", "https://discord.example/second"],
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert poster.send_breaking(item)
    assert len(seen) == 2
    assert json.loads(seen[0].content) == json.loads(seen[1].content)
    saved = store.get_article(item["id"])
    assert saved["state"] == "sent"
    assert saved["message_id"] == "message-1,message-2"


def test_fanout_partial_success_is_uncertain_and_not_retryable():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"id": "delivered"}) if calls == 1 else httpx.Response(500)

    store = Store()
    item = make_article(store)
    poster = Poster(
        store,
        ["https://discord.example/first", "https://discord.example/second"],
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert not poster.send_breaking(item)
    assert store.get_article(item["id"])["state"] == "uncertain"


def test_fanout_all_clear_failures_are_retryable():
    store = Store()
    item = make_article(store)
    poster = Poster(
        store,
        ["https://discord.example/first", "https://discord.example/second"],
        client_with(500),
    )
    assert not poster.send_breaking(item)
    assert store.get_article(item["id"])["state"] == "scored"


def test_additional_webhook_waits_until_start_time():
    store = Store()
    start_at = datetime(2026, 9, 17, 8, tzinfo=timezone.utc)
    poster = Poster(
        store,
        "https://discord.example/primary",
        client_with(200),
        additional_webhook_urls=["https://discord.example/additional"],
        additional_start_at=start_at,
    )

    assert poster._active_webhook_urls(datetime(2026, 9, 17, 7, 59, tzinfo=timezone.utc)) == (
        "https://discord.example/primary",
    )
    assert poster._active_webhook_urls(start_at) == (
        "https://discord.example/primary",
        "https://discord.example/additional",
    )
