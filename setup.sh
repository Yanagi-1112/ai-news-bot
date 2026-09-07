#!/usr/bin/env bash
# 初回設定を対話だけで行う。入力した秘密値を端末表示・ログ出力しない。
set -euo pipefail

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker と Docker Compose が必要です。https://docs.docker.com/engine/install/ を参照して導入してください。"
  exit 1
fi

if [[ -f .env ]]; then
  read -r -p ".env は既にあります。上書きしますか？ [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "中止しました。"; exit 0; }
fi

read -r -s -p "Discord Webhook URL: " webhook
echo
echo "LLMプロバイダを選択してください: 1) OpenAI 2) Gemini 3) DeepSeek 4) スタブで試す"
read -r -p "番号 [1-4]: " provider
case "$provider" in
  1) base_url="https://api.openai.com/v1"; default_model="gpt-5.6-terra" ;;
  2) base_url="https://generativelanguage.googleapis.com/v1beta/openai/"; default_model="gemini-3.8-flash" ;;
  3) base_url="https://api.deepseek.com"; default_model="deepseek-v4-flash" ;;
  4) base_url="stub"; default_model="stub" ;;
  *) echo "1〜4を選んでください。"; exit 1 ;;
esac
if [[ "$provider" == 4 ]]; then
  api_key="stub"
else
  read -r -s -p "LLM APIキー: " api_key
  echo
fi
read -r -p "モデル名 [$default_model]: " model
model="${model:-$default_model}"

umask 077
cat > .env <<EOF
DISCORD_WEBHOOK_URL=$webhook
LLM_BASE_URL=$base_url
LLM_API_KEY=$api_key
LLM_MODEL=$model
POST_HOUR_JST=8
BREAKING_THRESHOLD=90
EOF
chmod 600 .env
echo "設定ファイルを作成しました。イメージをビルドして起動します。"
docker compose up -d --build
docker compose exec newsbot python -m bot.main --check-config
read -r -p "Discordへテスト投稿しますか？ [y/N] " send_test
if [[ "$send_test" =~ ^[Yy]$ ]]; then
  docker compose exec newsbot python -m bot.main --send-test --yes
fi
