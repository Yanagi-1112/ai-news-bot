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

`DIGEST_MIN_SCORE`（既定60）未満の記事はダイジェストに載せません。速報は公式情報源・`breaking=true`・`BREAKING_THRESHOLD`以上の候補のみ。公開日が取得できる記事は公開日、それ以外は初回取得日で48時間の鮮度を確認します。巡回はJST毎時00分・30分、ダイジェストは8時の巡回から処理します。

LLM採点の不正応答・通信失敗は次の巡回へ持ち越し、候補ごとに最大3回で打ち切ります。DeepSeekの公式APIでは思考モードを無効にして短いJSON採点を行います。送信直前に日次枠をDBに保存し、応答不明・プロセス停止時は同日の追加送信を抑えます。到達不明の枠はDiscord実投稿と照合してから扱い、DBの予約だけを安易に消さないでください。

更新は、未コミット変更がなく、更新先tagに現在のコミットが含まれる場合だけ実行します。ローカル修正を含まないtagへの巻き戻りは停止します。DBバックアップにはSQLite backup APIを使い、バックアップが失敗した場合も更新を中止します。

更新は `./manage.sh update`、ひとつ前のリリースへ戻す場合は `./manage.sh rollback` を使います。どちらもリリースtagだけを対象にし、更新前にDBを `data/backups/` へ保存します。

投稿が来ない場合は、まず `./manage.sh status` と `./manage.sh logs` を確認してください。heartbeatが古い場合は `docker compose up -d --build` で再起動します。

## Webhookまたはキーが漏洩した場合

1. Discord側で該当Webhookを削除し、新しいWebhookを発行します。
2. LLMの管理画面でキーを失効させ、新しいキーを発行します。
3. `.env` の該当値を更新します。
4. `docker compose up -d --build` を実行して再起動します。
