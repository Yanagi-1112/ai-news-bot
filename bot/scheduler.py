"""30分ごとの単一tickを直列に実行するオーケストレーター。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
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

    def _fresh(self, articles: list[dict], now: datetime) -> list[dict]:
        """公開日を優先し、日付不明の情報源は初回取得日で鮮度を判定する。"""
        fresh = []
        for article in articles:
            stamp = None
            for value in (article.get("published_at"), article.get("first_seen_at")):
                if not value:
                    continue
                for parse in (datetime.fromisoformat, parsedate_to_datetime):
                    try:
                        stamp = parse(value)
                        if stamp.tzinfo is None:
                            stamp = stamp.replace(tzinfo=timezone.utc)
                        break
                    except (ValueError, TypeError, OverflowError):
                        continue
                if stamp is not None:
                    break
            if stamp is not None and stamp < now - timedelta(hours=48):
                self.store.update_article(article["id"], state="skipped")
            else:
                fresh.append(article)
        return fresh

    def _deliver(self, day: str, kind: str, articles: list[dict], send) -> bool:
        if not self.store.reserve_delivery(day, kind):
            return False
        # 例外・強制終了では予約を残す。到達不明の投稿を別候補で重ねない。
        success = send()
        retry_safe = all(self.store.get_article(a["id"])["state"] == "scored" for a in articles)
        self.store.finish_delivery(day, kind, success=success, retry_safe=retry_safe)
        return success

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
        new = self._fresh(self.store.get_articles("new"), now)[:30]
        self.curator.curate(new)
        outputs: list[str] = []
        date_jst = now.date().isoformat()
        # 速報は公式情報源だけで、スコアしきい値と日次上限をDBで強制する。
        for article in self._fresh(self.store.get_articles("scored"), now):
            if self.store.breaking_count(date_jst) or not article["breaking"] or article["source_category"] != "official" or (article["score"] or 0) < self.settings.breaking_threshold:
                continue
            content = build_breaking(article)
            outputs.append(content)
            if not dry_run and self._deliver(date_jst, "breaking", [article], lambda: self.poster.send_breaking(article)):
                self.store.increment_breaking(date_jst)
                self.store.mark_breaking_article(date_jst, article["id"])
            break
        # 時刻を逃しても、同一JST日に未送信なら次のtickで追いつく。
        # 48時間より古い候補は鮮度切れとしてダイジェストに載せない（速報bot
        # なので、送り損ねた古いニュースが何日も後に再浮上するのを防ぐ）。
        candidates = [article for article in self._fresh(self.store.get_articles("scored"), now)
                      if (article["score"] or 0) >= self.settings.digest_min_score]
        candidates.sort(key=lambda a: (a["score"] or 0), reverse=True)
        if now.hour >= self.settings.post_hour_jst and not self.store.digest_sent(date_jst) and candidates:
            breaking = self.store.breaking_article(date_jst)
            content = build_digest(candidates, now.date(), breaking)
            outputs.append(content)
            if not dry_run and self._deliver(date_jst, "digest", candidates[:5], lambda: self.poster.send_digest(candidates[:5], now.date(), breaking)):
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
