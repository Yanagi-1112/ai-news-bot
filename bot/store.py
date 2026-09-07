"""記事と投稿履歴を保存するSQLite層。

投稿状態を先に uncertain にすることで、通信の成否が不明なときの重複送信を防ぐ。
"""
from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
import sqlite3
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """計測パラメータと末尾スラッシュを取り除いた比較用URLを返す。"""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not (k.lower().startswith("utm_") or k.lower() in {"fbclid", "gclid", "mc_cid", "mc_eid"})]
    # 比較用なのでルートURLの / も含めて末尾スラッシュを統一する。
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


class Store:
    """SQLiteの小さなリポジトリ。row_factoryにより呼び出し側を読みやすくする。"""
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # 起動時tickの完了後、APSchedulerのworkerへ引き継ぐ。
        # schedulerはmax_instances=1でtickを直列実行するため同時利用しない。
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
          id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
          source_id TEXT NOT NULL, source_category TEXT NOT NULL, published_at TEXT,
          first_seen_at TEXT NOT NULL, summary TEXT, score INTEGER, score_reason TEXT,
          headline_ja TEXT, summary_ja TEXT, breaking INTEGER NOT NULL DEFAULT 0,
          state TEXT NOT NULL DEFAULT 'new', message_id TEXT
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_cache (
          source_id TEXT PRIMARY KEY, etag TEXT, last_modified TEXT
        );
        """)
        self.conn.commit()

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT NOT EXISTS(SELECT 1 FROM articles)").fetchone()[0] == 1

    def is_initialized(self) -> bool:
        """初回の既読化完了を返す。

        最初の巡回が全情報源の障害で0件でも完了を記録し、次に現れた新着を
        過去記事として捨てないためのフラグである。
        """
        return self.get_meta("initialized") == "1"

    def mark_initialized(self) -> None:
        self.set_meta("initialized", "1")

    def add_article(self, article: dict[str, Any], *, initial: bool = False) -> int | None:
        """URLと類似タイトルを照合して新規記事だけを入れる。"""
        url = normalize_url(article["url"])
        if self.conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone():
            return None
        title = article["title"].strip()
        # 類似判定は直近500件に限定する。全件走査だと運用数ヶ月でtickが重くなる。
        for row in self.conn.execute("SELECT title FROM articles ORDER BY id DESC LIMIT 500"):
            if SequenceMatcher(None, title.lower(), row["title"].lower()).ratio() > 0.9:
                return None
        state = "skipped" if initial else article.get("state", "new")
        cur = self.conn.execute("""INSERT INTO articles
          (url,title,source_id,source_category,published_at,first_seen_at,summary,state)
          VALUES (?,?,?,?,?,?,?,?)""", (url, title, article["source_id"], article["source_category"],
           article.get("published_at"), article.get("first_seen_at") or datetime.now().isoformat(), article.get("summary", ""), state))
        self.conn.commit()
        return int(cur.lastrowid)

    def add_articles(self, articles: Iterable[dict[str, Any]], *, initial: bool = False) -> list[int]:
        return [item for a in articles if (item := self.add_article(a, initial=initial)) is not None]

    def get_articles(self, state: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM articles" + (" WHERE state = ?" if state else "") + " ORDER BY id"
        rows = self.conn.execute(query, (state,) if state else ()).fetchall()
        return [dict(row) for row in rows]

    def get_article(self, article_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        return dict(row) if row else None

    def update_article(self, article_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {"score", "score_reason", "headline_ja", "summary_ja", "breaking", "state", "message_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"更新できない項目です: {unknown}")
        values = list(fields.values()) + [article_id]
        self.conn.execute(f"UPDATE articles SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?", values)
        self.conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    def digest_sent(self, date_jst: str) -> bool:
        return self.get_meta("digest_sent_date") == date_jst

    def mark_digest_sent(self, date_jst: str) -> None:
        self.set_meta("digest_sent_date", date_jst)

    def breaking_count(self, date_jst: str) -> int:
        return int(self.get_meta(f"breaking_count:{date_jst}") or "0")

    def increment_breaking(self, date_jst: str) -> None:
        self.set_meta(f"breaking_count:{date_jst}", str(self.breaking_count(date_jst) + 1))

    def mark_breaking_article(self, date_jst: str, article_id: int) -> None:
        """当日ダイジェストで再掲する、実際に送信済みの速報を記録する。"""
        self.set_meta(f"breaking_article:{date_jst}", str(article_id))

    def breaking_article(self, date_jst: str) -> dict[str, Any] | None:
        value = self.get_meta(f"breaking_article:{date_jst}")
        return self.get_article(int(value)) if value else None

    def source_headers(self, source_id: str) -> tuple[str | None, str | None]:
        row = self.conn.execute("SELECT etag,last_modified FROM source_cache WHERE source_id=?", (source_id,)).fetchone()
        return (row["etag"], row["last_modified"]) if row else (None, None)

    def save_source_headers(self, source_id: str, etag: str | None, last_modified: str | None) -> None:
        self.conn.execute("""INSERT INTO source_cache(source_id,etag,last_modified) VALUES(?,?,?)
        ON CONFLICT(source_id) DO UPDATE SET etag=excluded.etag,last_modified=excluded.last_modified""", (source_id, etag, last_modified))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
