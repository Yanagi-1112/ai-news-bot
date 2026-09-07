"""登録済みのRSS、公式一覧、公開APIから記事候補を集める。

本文ページにはアクセスしない。これは取得量を抑えるだけでなく、登録情報源以外の
入力を処理対象に広げないための境界でもある。
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any

from bs4 import BeautifulSoup
import feedparser
import httpx

from .store import Store

LOG = logging.getLogger(__name__)
TIMEOUT = 15.0


class Collector:
    def __init__(self, store: Store, client: httpx.Client | None = None) -> None:
        self.store = store
        self.client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get(self, source: dict[str, Any], url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """ETag対応と429の小さな再試行を一箇所に集める。"""
        etag, modified = self.store.source_headers(source["id"])
        headers = {"User-Agent": "ai-news-bot/0.1"}
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        for attempt in range(3):
            response = self.client.get(url, params=params, headers=headers, timeout=TIMEOUT)
            if response.status_code != 429:
                if response.status_code != 304:
                    response.raise_for_status()
                    self.store.save_source_headers(source["id"], response.headers.get("etag"), response.headers.get("last-modified"))
                return response
            retry = response.headers.get("Retry-After")
            try:
                delay = min(float(retry), 10.0) if retry else min(2**attempt, 10.0)
            except ValueError:
                delay = min(2**attempt, 10.0)
            time.sleep(delay)
        response.raise_for_status()
        return response

    @staticmethod
    def _article(source: dict[str, Any], url: str, title: str, summary: str = "", published_at: str | None = None) -> dict[str, Any]:
        return {"url": url, "title": title[:500], "summary": summary[:2000], "published_at": published_at,
                "source_id": source["id"], "source_category": source["category"], "first_seen_at": datetime.now(timezone.utc).isoformat()}

    def _rss(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._get(source, source["url"])
        if response.status_code == 304:
            return []
        feed = feedparser.parse(response.content)
        # bozoは軽微な文法警告でも立つため、entriesが1件も取れない場合だけ異常扱いにする。
        if getattr(feed, "bozo", False) and not feed.entries:
            raise ValueError(f"RSSが不正です: {source['id']}")
        return [self._article(source, e.link, e.title, getattr(e, "summary", ""), getattr(e, "published", None))
                for e in feed.entries if getattr(e, "link", None) and getattr(e, "title", None)]

    def _html_list(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._get(source, source["url"])
        if response.status_code == 304:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        selector = source.get("selector", "a")
        articles: list[dict[str, Any]] = []
        for link in soup.select(selector):
            href = link.get("href")
            title = link.get_text(" ", strip=True)
            if not href or not title:
                continue
            articles.append(self._article(source, str(httpx.URL(source["url"]).join(href)), title))
        return articles

    def _hn_algolia(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        articles: list[dict[str, Any]] = []
        for term in source.get("queries", ["AI", "LLM", "Claude", "GPT", "Gemini"]):
            response = self._get(source, source["url"], {"tags": "story", "query": term, "hitsPerPage": 30})
            if response.status_code == 304:
                continue
            for hit in response.json().get("hits", []):
                if int(hit.get("points") or 0) < int(source.get("min_points", 30)):
                    continue
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                title = hit.get("title") or hit.get("story_title")
                if title:
                    articles.append(self._article(source, url, title, hit.get("story_text") or "", hit.get("created_at")))
        return articles

    def _hf_models(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._get(source, source["url"], {"sort": "lastModified", "direction": "-1", "limit": 30})
        if response.status_code == 304:
            return []
        items = response.json()
        articles: list[dict[str, Any]] = []
        for model in items:
            if int(model.get("likes") or 0) < int(source.get("min_likes", 5)) and int(model.get("downloads") or 0) < int(source.get("min_downloads", 100)):
                continue
            model_id = model.get("modelId")
            if model_id:
                articles.append(self._article(source, f"https://huggingface.co/{model_id}", model_id, "Hugging Faceで更新されたモデル", model.get("lastModified")))
        return articles

    def collect(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """一情報源の故障で全体を止めず、候補は後段の上限まで返す。"""
        handlers = {"rss": self._rss, "html_list": self._html_list, "hn_algolia": self._hn_algolia, "hf_models": self._hf_models}
        collected: list[dict[str, Any]] = []
        for source in sources:
            try:
                collected.extend(handlers[source["type"]](source))
            except Exception as exc:  # ネットワーク・形式崩れは情報源単位で隔離する。
                LOG.warning("情報源 %s の収集に失敗しました: %s", source["id"], type(exc).__name__)
        return collected
