"""30分ごとの単一tickを直列に実行するオーケストレーター。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from .collector import Collector
from .config import Settings
from .curator import Curator
from .poster import Poster, build_breaking, build_digest
from .store import Store

JST = ZoneInfo("Asia/Tokyo")
LOG = logging.getLogger(__name__)


class NewsScheduler:
    def __init__(self, store: Store, collector: Collector, curator: Curator, poster: Poster, settings: Settings, sources: list[dict]) -> None:
        self.store, self.collector, self.curator, self.poster = store, collector, curator, poster
        self.settings, self.sources = settings, sources

    def tick(self, now: datetime | None = None, *, dry_run: bool = False) -> list[str]:
        """1回分を直列実行する。dry_run時は呼び出し側のインメモリDBを使う。"""
        now = (now or datetime.now(JST)).astimezone(JST)
        initial = self.store.is_empty() and not self.store.is_initialized()
        collected = self.collector.collect(self.sources)
        self.store.add_articles(collected, initial=initial)
        if initial:
            self.store.mark_initialized()
            self._heartbeat()
            return []
        new = self.store.get_articles("new")[:30]
        self.curator.curate(new)
        outputs: list[str] = []
        date_jst = now.date().isoformat()
        # 速報は公式情報源だけで、スコアしきい値と日次上限をDBで強制する。
        for article in self.store.get_articles("scored"):
            if self.store.breaking_count(date_jst) or article["source_category"] != "official" or (article["score"] or 0) < self.settings.breaking_threshold:
                continue
            content = build_breaking(article)
            outputs.append(content)
            if not dry_run and self.poster.send_breaking(article):
                self.store.increment_breaking(date_jst)
                self.store.mark_breaking_article(date_jst, article["id"])
            break
        # 時刻を逃しても、同一JST日に未送信なら次のtickで追いつく。
        # 48時間より古い候補は鮮度切れとしてダイジェストに載せない（速報bot
        # なので、送り損ねた古いニュースが何日も後に再浮上するのを防ぐ）。
        fresh_limit = (now - timedelta(hours=48)).astimezone(timezone.utc)
        candidates = []
        for article in self.store.get_articles("scored"):
            try:
                seen = datetime.fromisoformat(article["first_seen_at"])
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                seen = now
            if seen < fresh_limit:
                self.store.update_article(article["id"], state="skipped")
                continue
            candidates.append(article)
        candidates.sort(key=lambda a: (a["score"] or 0), reverse=True)
        if now.hour >= self.settings.post_hour_jst and not self.store.digest_sent(date_jst) and candidates:
            breaking = self.store.breaking_article(date_jst)
            content = build_digest(candidates, now.date(), breaking)
            outputs.append(content)
            if not dry_run and self.poster.send_digest(candidates[:5], now.date(), breaking):
                self.store.mark_digest_sent(date_jst)
        self._heartbeat()
        return outputs

    def _heartbeat(self) -> None:
        try:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            (self.settings.data_dir / "heartbeat").touch()
        except OSError as exc:
            LOG.warning("heartbeatを更新できませんでした: %s", type(exc).__name__)

    def serve(self) -> None:
        scheduler = BlockingScheduler(timezone=JST)
        scheduler.add_job(self.tick, "cron", minute="0,30", second=0, max_instances=1, coalesce=True, misfire_grace_time=600)
        self.tick()  # 起動直後にも1回実行し、初回既読化と停止復帰を早める。
        scheduler.start()
