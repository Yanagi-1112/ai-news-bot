"""CLI入口。通常運用、通信なしの確認、明示的なテスト投稿を分ける。"""
from __future__ import annotations

import argparse
import logging
import sys

from .collector import Collector
from .config import load_settings, load_sources, validate_config
from .curator import Curator
from .poster import Poster
from .scheduler import NewsScheduler
from .store import Store


def build_runtime(*, memory: bool = False):
    settings = load_settings()
    store = Store(":memory:" if memory else settings.data_dir / "newsbot.sqlite3")
    if memory:
        # dry-run用の空DBをそのまま使うと「初回既読化」で全記事がskippedになり
        # 何も出力されない。dry-runでは初回化を済ませた扱いにして採点まで通す。
        store.mark_initialized()
    collector = Collector(store)
    curator = Curator(store, settings)
    poster = Poster(store, settings.discord_webhook_url)
    return NewsScheduler(store, collector, curator, poster, settings, load_sources())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIニュースを収集・投稿します")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="外部投稿・永続DB変更なしで1tick実行")
    mode.add_argument("--check-config", action="store_true", help="設定ファイルのみ検証")
    mode.add_argument("--send-test", action="store_true", help="Discordにテスト投稿")
    parser.add_argument("--yes", action="store_true", help="--send-test の確認を省略")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.check_config:
        errors = validate_config()
        if errors:
            print("設定エラー:", *errors, sep="\n- ")
            return 1
        print("設定は有効です。")
        return 0
    errors = validate_config()
    if errors:
        print("設定エラー:", *errors, sep="\n- ", file=sys.stderr)
        return 1
    runtime = build_runtime(memory=args.dry_run)
    try:
        if args.dry_run:
            for content in runtime.tick(dry_run=True):
                print(content)
            return 0
        if args.send_test:
            if not args.yes and input("Discordにテスト投稿しますか？ [y/N] ").lower() not in {"y", "yes"}:
                print("中止しました。")
                return 0
            return 0 if runtime.poster.send_test() else 1
        runtime.serve()
        return 0
    finally:
        runtime.collector.close()
        runtime.poster.close()
        runtime.store.close()


if __name__ == "__main__":
    raise SystemExit(main())
