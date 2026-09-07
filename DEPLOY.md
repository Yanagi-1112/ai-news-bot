# KAGOYAクラウドVPSへの導入

Ubuntu VPSにDockerとDocker Composeを導入してから、次を実行します。

```bash
git clone https://github.com/Yanagi-1112/ai-news-bot.git
cd ai-news-bot
git checkout "$(git tag --sort=-version:refname | head -n 1)"   # 最新リリースtagに固定（推奨）
./setup.sh
```

セットアップ中にWebhook URLとLLMキーを入力します。入力値は `.env` にだけ保存されます。起動後は `./manage.sh status` で稼働状態を確認し、必要なら `./manage.sh logs` でログを見ます。テスト投稿はセットアップ時、または `docker compose exec newsbot python -m bot.main --send-test` で確認できます。

## 日常運用

更新は `./manage.sh update`、ひとつ前のリリースへ戻す場合は `./manage.sh rollback` を使います。どちらもリリースtagだけを対象にし、更新前にDBを `data/backups/` へ保存します。

投稿が来ない場合は、まず `./manage.sh status` と `./manage.sh logs` を確認してください。heartbeatが古い場合は `docker compose up -d --build` で再起動します。

## Webhookまたはキーが漏洩した場合

1. Discord側で該当Webhookを削除し、新しいWebhookを発行します。
2. LLMの管理画面でキーを失効させ、新しいキーを発行します。
3. `.env` の該当値を更新します。
4. `docker compose up -d --build` を実行して再起動します。
