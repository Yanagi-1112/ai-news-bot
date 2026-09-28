"""Discord Webhookへの投稿と、表示用Markdownの組み立てを担当する。"""
from __future__ import annotations

from datetime import date, datetime, timezone
import logging
from typing import Any, Iterable

import httpx

from .store import Store

LOG = logging.getLogger(__name__)
MAX_DISCORD_LENGTH = 2000


def _line(article: dict[str, Any], preview: bool) -> str:
    headline = article.get("headline_ja") or article["title"]
    url = article["url"] if preview else f"<{article['url']}>"
    return f"**{headline}**\n{article.get('summary_ja') or ''}\n{url}" if preview else f"- {headline} {url}"


def build_breaking(article: dict[str, Any]) -> str:
    return f"🚨 速報\n{_line(article, preview=True)}"[:MAX_DISCORD_LENGTH]


def _digest(articles: Iterable[dict[str, Any]], day: date, breaking: dict[str, Any] | None = None) -> tuple[str, list[int]]:
    """トップはプレビューを出し、次点は抑止する。長い場合は次点から削る。"""
    items = list(articles)[:5]
    if not items:
        return "", []
    parts = [f"📰 AIニュース {day.isoformat()}", _line(items[0], preview=True)]
    if len("\n".join(parts)) > MAX_DISCORD_LENGTH:
        # URL途中で切れた投稿を送信済みとしない。次の収まる記事を先頭にする。
        return _digest(items[1:], day, breaking)
    included = [items[0]["id"]]
    for article in items[1:]:
        candidate = "\n".join(parts + [_line(article, preview=False)])
        if len(candidate) > MAX_DISCORD_LENGTH:
            break
        parts.append(_line(article, preview=False))
        included.append(article["id"])
    if breaking:
        breaking_line = f"本日の速報: {breaking.get('headline_ja') or breaking['title']} <{breaking['url']}>"
        if len("\n".join(parts + [breaking_line])) <= MAX_DISCORD_LENGTH:
            parts.append(breaking_line)
    return "\n".join(parts), included


def build_digest(articles: Iterable[dict[str, Any]], day: date, breaking: dict[str, Any] | None = None) -> str:
    return _digest(articles, day, breaking)[0]


class Poster:
    def __init__(self, store: Store, webhook_url: str | Iterable[str], client: httpx.Client | None = None,
                 username: str | None = None, avatar_url: str | None = None,
                 additional_webhook_urls: Iterable[str] = (),
                 additional_start_at: datetime | None = None) -> None:
        self.store = store
        raw_urls = (webhook_url,) if isinstance(webhook_url, str) else tuple(webhook_url)
        immediate_urls = tuple(dict.fromkeys(url.strip() for url in raw_urls if url.strip()))
        delayed_urls = tuple(dict.fromkeys(url.strip() for url in additional_webhook_urls if url.strip()))
        delayed_urls = tuple(url for url in delayed_urls if url not in immediate_urls)
        self.webhook_urls = immediate_urls + delayed_urls
        if not self.webhook_urls:
            raise ValueError("Discord Webhook URLが1件もありません")
        # 単一投稿先を前提にした外部コードとの互換用。
        self.webhook_url = self.webhook_urls[0]
        self.immediate_webhook_urls = immediate_urls
        self.additional_webhook_urls = delayed_urls
        self.additional_start_at = additional_start_at
        # Webhook既定の名前・アイコンをメッセージ単位で上書きする（未指定なら既定のまま）。
        self.username, self.avatar_url = username, avatar_url
        self.client = client or httpx.Client(timeout=15.0)
        self._owns_client = client is None

    def _payload(self, content: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"content": content, "allowed_mentions": {"parse": []}}
        if self.username:
            payload["username"] = self.username
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url
        return payload

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _active_webhook_urls(self, now: datetime | None = None) -> tuple[str, ...]:
        """開始時刻までは追加先を除外し、既存配信だけを継続する。"""
        if not self.additional_webhook_urls:
            return self.immediate_webhook_urls
        current = now or datetime.now(timezone.utc)
        if self.additional_start_at is None or current >= self.additional_start_at:
            return self.immediate_webhook_urls + self.additional_webhook_urls
        return self.immediate_webhook_urls

    def _send(self, content: str, article_ids: list[int]) -> bool:
        """全投稿先へ同じ紙面を送り、部分成功時も重複を防ぐ。"""
        webhook_urls = self._active_webhook_urls()
        if not webhook_urls:
            # 予約開始前は未配信のまま保持し、開始後の巡回で送る。
            return False
        for article_id in article_ids:
            self.store.update_article(article_id, state="uncertain")
        message_ids: list[str] = []
        failed_safely = 0
        uncertain = False
        for index, webhook_url in enumerate(webhook_urls, start=1):
            try:
                response = self.client.post(webhook_url + "?wait=true", json=self._payload(content), timeout=15.0)
            except httpx.ConnectError:
                failed_safely += 1
                LOG.warning("Discord投稿先%dへ接続できませんでした", index)
                continue
            except httpx.TimeoutException:
                uncertain = True
                LOG.warning("Discord投稿先%dの応答がタイムアウトしました。重複防止のため再送しません", index)
                continue
            except httpx.RequestError:
                uncertain = True
                LOG.warning("Discord投稿先%dへの接続結果が不明です。重複防止のため再送しません", index)
                continue
            if not 200 <= response.status_code < 300:
                failed_safely += 1
                LOG.warning("Discord投稿先%dへの投稿に失敗しました: HTTP %s", index, response.status_code)
                continue
            try:
                message_ids.append(str(response.json().get("id", "")))
            except ValueError:
                message_ids.append("")

        if len(message_ids) == len(webhook_urls):
            joined_message_ids = ",".join(filter(None, message_ids))
            for article_id in article_ids:
                self.store.update_article(article_id, state="sent", message_id=joined_message_ids)
            return True

        # 全投稿先へ明確に到達しなかった場合だけ、次のtickで安全に再試行する。
        # 一部成功または結果不明が1件でもあれば uncertain のままにする。
        if not message_ids and not uncertain and failed_safely == len(webhook_urls):
            for article_id in article_ids:
                self.store.update_article(article_id, state="scored")
        return False

    def send_breaking(self, article: dict[str, Any]) -> bool:
        return self._send(build_breaking(article), [article["id"]])

    def send_digest(self, articles: list[dict[str, Any]], day: date, breaking: dict[str, Any] | None = None) -> bool:
        if not articles:
            return False
        content, included = _digest(articles, day, breaking)
        return self._send(content, included) if included else False

    def send_test(self) -> bool:
        """通常記事の状態には触れない固定疎通メッセージ。"""
        webhook_urls = self._active_webhook_urls()
        if not webhook_urls:
            return False
        success = True
        for webhook_url in webhook_urls:
            try:
                response = self.client.post(webhook_url + "?wait=true", json=self._payload("[TEST] 接続テストです。この名前とアイコンで配信されます。"), timeout=15.0)
                success = success and 200 <= response.status_code < 300
            except httpx.RequestError:
                success = False
        return success
