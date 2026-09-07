#!/usr/bin/env bash
# 日常運用コマンド。更新・ロールバックは未検証のmainではなくリリースtagを使う。
set -euo pipefail

backup_and_start() {
  mkdir -p data/backups
  # DBはnamed volume内にあるため、稼働中コンテナからホストのバックアップ先へ取り出す。
  docker compose cp newsbot:/data/newsbot.sqlite3 "data/backups/newsbot-$(date +%Y%m%d-%H%M%S).sqlite3" 2>/dev/null || true
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
    git fetch --tags
    target="$(git tag --sort=-version:refname | head -n 1)"
    [[ -n "$target" ]] || { echo "リリースtagが見つかりません。"; exit 1; }
    git checkout "$target"
    backup_and_start
    ;;
  rollback)
    git fetch --tags
    current="$(git describe --tags --exact-match 2>/dev/null || true)"
    [[ -n "$current" ]] || { echo "現在のリリースtagを判定できません。"; exit 1; }
    # 降順一覧で現在tagの直後が、意味上の「ひとつ前」のリリースである。
    target="$(git tag --sort=-version:refname | awk -v current="$current" '$0 == current { getline; print; exit }')"
    [[ -n "$target" ]] || { echo "1つ前のリリースtagが見つかりません。"; exit 1; }
    git checkout "$target"
    backup_and_start
    ;;
  *)
    echo "使い方: $0 {status|logs [件数]|update|rollback}"
    exit 1
    ;;
esac
