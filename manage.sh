#!/usr/bin/env bash
# 日常運用コマンド。更新・ロールバックは未検証のmainではなくリリースtagを使う。
set -euo pipefail

backup_and_start() {
  mkdir -p data/backups
  # liveファイルの単純コピーは避ける。バックアップ失敗時は更新しない。
  docker compose exec -T newsbot python -c 'import sqlite3; s=sqlite3.connect("/data/newsbot.sqlite3"); d=sqlite3.connect("/data/update-backup.sqlite3"); s.backup(d); d.close(); s.close()'
  docker compose cp newsbot:/data/update-backup.sqlite3 "data/backups/newsbot-$(date +%Y%m%d-%H%M%S).sqlite3"
  git checkout "$target"
  docker compose up -d --build
}

case "${1:-}" in
  status)
    docker compose ps
    # heartbeatはnamed volume内にあるため、ホスト側のdata/ではなくコンテナ内を確認する。
    docker compose exec -T newsbot sh -c 'if [ -f /data/heartbeat ]; then echo "heartbeat経過秒: $(( $(date +%s) - $(stat -c %Y /data/heartbeat) ))"; else echo "heartbeat: 未作成"; fi' || true
    ;;
  logs) docker compose logs --tail "${2:-100}" ;;
  update)
    [[ -z "$(git status --porcelain)" ]] || { echo "未コミットの変更があります。更新を中止しました。"; exit 1; }
    git fetch --tags
    target="$(git tag --sort=-version:refname | head -n 1)"
    [[ -n "$target" ]] || { echo "リリースtagが見つかりません。"; exit 1; }
    git merge-base --is-ancestor HEAD "$target" || { echo "このリリースには現在の修正が含まれていません。更新を中止しました。"; exit 1; }
    backup_and_start
    ;;
  rollback)
    [[ -z "$(git status --porcelain)" ]] || { echo "未コミットの変更があります。復旧を中止しました。"; exit 1; }
    git fetch --tags
    current="$(git describe --tags --exact-match 2>/dev/null || true)"
    [[ -n "$current" ]] || { echo "現在のリリースtagを判定できません。"; exit 1; }
    # 降順一覧で現在tagの直後が、意味上の「ひとつ前」のリリースである。
    target="$(git tag --sort=-version:refname | awk -v current="$current" '$0 == current { getline; print; exit }')"
    [[ -n "$target" ]] || { echo "1つ前のリリースtagが見つかりません。"; exit 1; }
    backup_and_start
    ;;
  *)
    echo "使い方: $0 {status|logs [件数]|update|rollback}"
    exit 1
    ;;
esac
