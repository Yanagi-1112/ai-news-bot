"""Discord Webhookへの投稿と、表示用Markdownの組み立てを担当する。"""
from __future__ import annotations

from datetime import date
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


def build_digest(articles: Iterable[dict[str, Any]], day: date, breaking: dict[str, Any] | None = None) -> str:
    """トップはプレビューを出し、次点は抑止する。長い場合は次点から削る。"""
    items = list(articles)[:5]
    if not items:
        return ""
    parts = [f"📰 AIニュース {day.isoformat()}", _line(items[0], preview=True)]
    for article in items[1:]:
        candidate = "\n".join(parts + [_line(article, preview=False)])
        if len(candidate) > MAX_DISCORD_LENGTH:
            break
        parts.append(_line(article, preview=False))
    if breaking:
        breaking_line = f"本日の速報: {breaking.get('headline_ja') or breaking['title']} <{breaking['url']}>"
        if len("\n".join(parts + [breaking_line])) <= MAX_DISCORD_LENGTH:
            parts.append(breaking_line)
    return "\n".join(parts)[:MAX_DISCORD_LENGTH]


class Poster:
    def __init__(self, store: Store, webhook_url: str, client: httpx.Client | None = None,
                 username: str | None = None, avatar_url: str | None = None) -> None:
        self.store, self.webhook_url = store, webhook_url
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

    def _send(self, content: str, article_ids: list[int]) -> bool:
        """送信直前の uncertain 化が、タイムアウト時の重複投稿を防ぐ。"""
        for article_id in article_ids:
            self.store.update_article(article_id, state="uncertain")
        try:
            response = self.client.post(self.webhook_url + "?wait=true", json=self._payload(content), timeout=15.0)
        except httpx.ConnectError:
            # 接続自体に失敗＝リクエストは届いていないので、再送候補に戻して安全。
            for article_id in article_ids:
                self.store.update_article(article_id, state="scored")
            LOG.warning("Discordに接続できませんでした。次の機会に再送します")
            return False
        except httpx.TimeoutException:
            LOG.warning("Discord応答がタイムアウトしました。重複防止のため再送しません")
            return False
        except httpx.RequestError:
            LOG.warning("Discordへの接続結果が不明です。重複防止のため再送しません")
            return False
        if not 200 <= response.status_code < 300:
            for article_id in article_ids:
                self.store.update_article(article_id, state="scored")
            LOG.warning("Discord投稿に失敗しました: HTTP %s", response.status_code)
            return False
        try:
            message_id = str(response.json().get("id", ""))
        except ValueError:
            message_id = ""
        for article_id in article_ids:
            self.store.update_article(article_id, state="sent", message_id=message_id)
        return True

    def send_breaking(self, article: dict[str, Any]) -> bool:
        return self._send(build_breaking(article), [article["id"]])

    def send_digest(self, articles: list[dict[str, Any]], day: date, breaking: dict[str, Any] | None = None) -> bool:
        if not articles:
            return False
        return self._send(build_digest(articles, day, breaking), [article["id"] for article in articles])

    def send_test(self) -> bool:
        """通常記事の状態には触れない固定疎通メッセージ。"""
        try:
            response = self.client.post(self.webhook_url + "?wait=true", json=self._payload("[TEST] 接続テストです。この名前とアイコンで配信されます。"), timeout=15.0)
            return 200 <= response.status_code < 300
        except httpx.RequestError:
            return False
