# ai-news-bot

AIの「ワクワクする」ニュースだけを厳選して、Discordに1日1回届けるbot。

新モデルのリリース、驚きのベンチマーク、話題のデモやOSSなど、
**技術者が「これ自分でも触ってみたい」と手を動かしたくなるニュース**をAIが選んで流します。
資金調達・人事などのビジネスニュースは流しません。

> **Status: 準備中（設計フェーズ）**
> 設計プランは [plans/active/](plans/active/) を参照してください。

## 予定している構成

```
collector（情報源を30分ごと巡回）
  → SQLite（既読管理・候補プール）
  → curator（LLMがワクワク度を採点）
  → poster（Discord Webhookへ投稿）
```

- 基本は1日1回の定時ダイジェスト（トップ1本＋次点2〜4本）
- 超大型ニュース（例: 主要モデルの新リリース）だけは即時速報（1日最大+1回）
- 選定基準はプロンプトファイルで管理し、コードを触らず調整可能

## デプロイ（予定）

KAGOYAクラウドVPS上で Docker Compose により稼働させます。

```bash
git clone https://github.com/Yanagi-1112/ai-news-bot.git
cd ai-news-bot
./setup.sh   # 対話形式でWebhook URL等を設定 → 自動起動
```

実装が入り次第、詳細な手順を `DEPLOY.md` に用意します。
