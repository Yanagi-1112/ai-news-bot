調査日: **2026年9月7日（JST）**。  
結論として、**公式RSS／公式ページ差分監視を主系統**にし、HN・Reddit・Hugging Face・GitHubを「発見と話題性判定」に使う構成が最も堅いです。  
月数ドル以内ならX監視は必須にせず、必要な公式アカウントだけ低頻度で補助監視します。速報投稿は必ず公式URLまたは公式GitHub Releaseで再確認し、HN等だけで投稿しない設計を推奨します。

## 推奨構成

- 5〜10分: 各社の公式RSS、RSSなし公式ページの差分監視
- 5分: HN Firebase と Reddit OAuth API
- 15分: Hugging Face の新規・更新モデル、監視対象GitHub Release
- 30〜60分: GitHub API検索、HF Trending、GitHub Trending
- 6〜12時間: smol.ai / TLDR AI RSSを見落とし検知に利用
- 1日1回に集約し、**公式の大規模モデル公開・重大ベンチマーク・注目OSSの急伸**だけ即時の2本目を許可

## 公式情報源

更新頻度は保証値ではなく、2026年8〜9月の掲載ペースを踏まえた運用目安です。RSSは5分、HTML差分は5〜10分ポーリングで十分です。

| 情報源 | アクセス手段 | 更新頻度の目安 | 速報性 / 信頼性 | 注意点 |
|---|---|---:|---|---|
| OpenAI News | [RSS](https://openai.com/news/rss.xml) / [News](https://openai.com/news/) | 数日〜週 | 5分以内 / 非常に高い | 製品変更はNewsより[Release Notes](https://openai.com/products/release-notes/)に先に出ることがある |
| Anthropic | [News](https://www.anthropic.com/news)、[Claude API Release Notes](https://platform.claude.com/docs/en/release-notes/overview) | 数日〜週 | 5〜10分 / 非常に高い | 公式RSSは確認できないため、一覧・Release Notesを差分監視 |
| Google AI | [Google AI RSS](https://blog.google/technology/ai/rss/) | 日〜週 | 5分以内 / 非常に高い | Google全体のAI記事も混ざるのでモデル名・DeepMind等で絞る |
| Google DeepMind | [Blog](https://deepmind.google/blog/) | 週〜月 | 5〜10分 / 非常に高い | 独立した公式RSSは確認できず、HTML差分＋Google AI RSS |
| Meta AI | [Meta AI Blog](https://ai.meta.com/blog/) | 週〜月 | 5〜10分 / 非常に高い | RSSなし。Llama等はGitHub/Hugging Faceも併用 |
| xAI | [xAI News](https://x.ai/news) | 数日〜週 | 5〜10分 / 非常に高い | RSSなし。X投稿の方が先行する場合がある |
| Mistral | [News](https://mistral.ai/news/)、[Release Notes](https://docs.mistral.ai/resources/release-notes)、[Changelog](https://docs.mistral.ai/resources/changelogs) | 数日〜週 | 5〜10分 / 非常に高い | RSSなし。NewsだけでなくAPI/モデル変更履歴も見る |

## 発見・話題性の情報源

| 情報源 | アクセス手段 | 無料枠・料金 | 速報性 | 信頼性・使い方 |
|---|---|---:|---|---|
| Hacker News Firebase | [`newstories.json`](https://hacker-news.firebaseio.com/v0/newstories.json)、[`item/<id>.json`](https://github.com/HackerNews/API) | 無料、公式はレート制限なしと記載 | 投稿からほぼ即時〜5分 | AI語彙、特定企業、Show HNを監視。公式発表より遅いこともあるが、開発者の熱量検知に強い |
| HN Algolia | [API](https://hn.algolia.com/api) の `search_by_date` | 無料利用可。明示的SLAなし | 数分〜十数分 | `AI`、`LLM`、`Show HN`、モデル名で検索。Firebaseより索引反映が遅れうるため補助 |
| Reddit | [Data API](https://www.reddit.com/dev/api/) / [制限](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki) | OAuthで無料枠 **100 QPM / client ID** | 投稿から5分程度 | `r/MachineLearning`、`r/LocalLLaMA`、`r/singularity` を `/new` で取得。投票・コメントが育つまで品質判断は数時間待つ |
| Reddit RSS | `https://www.reddit.com/r/LocalLLaMA/.rss` 等 | 無料だが恒久性・SLAなし | 数分〜不定 | RSSは補助のみ。本番はOAuth APIを使う。削除投稿の保持・再配信には[削除義務](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki)がある |
| Hugging Face: 新モデル | [Hub API](https://huggingface.co/docs/hub/api) の `https://huggingface.co/api/models?sort=lastModified&direction=-1` | Free token: **1,000 req/5分**、匿名: **500 req/5分**（[公式制限](https://huggingface.co/docs/hub/main/rate-limits)） | 5〜15分 | 新規・更新weightsの検知に非常に良い。作者allow-list、モデルカード、ライセンス確認を必須にする |
| Hugging Face Trending / Papers | [CLI/API案内](https://huggingface.co/docs/huggingface_hub/en/guides/cli)、[Papers Trending](https://huggingface.co/papers/trending) | 無料 | 数時間〜日 | 「今すぐ公開」ではなく、評価・注目を集めた候補の選別向け |
| GitHub Release / Webhook | [GitHub API](https://docs.github.com/en/rest/releases/releases) / Webhook | 無料。PATなら通常 **5,000 req/時** | Webhookは秒〜分、pollは5〜15分 | 重要OSSをallow-listで監視する最も堅い方法 |
| GitHub検索 | [`/search/repositories`](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories) | 未認証60 req/時、PAT 5,000 req/時。検索は別枠のため低頻度推奨 | 15〜30分 | `llm OR agent OR diffusion` と更新日を条件に検索し、スター増分を自前保存する |
| GitHub Trending | [Trending HTML](https://github.com/trending?since=daily&spoken_language_code=en) | 無料 | 数時間〜1日 | 公式APIは存在しないため、HTML取得は補助扱い。GitHub自身も[Trending REST APIはない](https://github.com/orgs/community/discussions/161519)と案内している |
| smol.ai AINews | [RSS](https://news.smol.ai/rss.xml) / [本体](https://news.smol.ai/) | 無料 | 数時間〜翌日 | Discord・X・Reddit横断の漏れ検知に有用。速報の根拠にはしない |
| TLDR AI | [RSS](https://buttondown.com/ai_news/rss) | 無料 | 数時間〜翌日 | smol.aiと同じく日次レビュー用。一次発表URLを抽出して使う |

## X / Twitter の扱い

| 手段 | 料金・速報性 | 判定 |
|---|---|---|
| [X公式API](https://docs.x.com/x-api/getting-started/pricing) | 従量課金。Post readは **$0.005/件**、前払いクレジット、月次3百万Post-read上限。filtered streamなら秒〜数十秒 | 最速だが、小規模botでは費用対効果が微妙。監視アカウントを厳選できる場合のみ |
| [twitterapi.io](https://twitterapi.io/pricing) | 表示価格は **$0.15 / 1,000 posts**、最低契約なし。poll間隔次第で数分 | 安価な補助策。ただし独立第三者サービスなので、規約・仕様変更・停止を前提にkill switchを持つ |
| Nitter | 公開インスタンス一覧は残るが、2026年8月のXによる停止要求後に不安定化。プロジェクト側もホスティング困難性を説明している | 本番依存は不可。RSS代替として採用しない |

Xを使わない場合でも、公式ブログ差分＋HN＋Redditで「技術者が触りたくなる」ニュースの大半は拾えます。使うなら、OpenAI / Anthropic / Google DeepMind / Meta AI / xAI / Mistral / Hugging Face / 有力OSS作者など**20〜30アカウントに限定**し、月額上限を$2程度に設定するのが安全です。

## RSSがない公式サイトの監視手法

1. **公式RSSを最優先**  
   壊れにくく、著者・公開時刻・URLが得やすいです。

2. **公式一覧ページの差分監視を次点にする**  
   `ETag` / `If-None-Match` と `Last-Modified` を使い、変更時だけ記事カードのURL・タイトル・日付を抽出してSQLiteの既知IDと比較します。本文全体のhashではなく、`main` や記事一覧の安定セレクタだけを比較してください。  
   [changedetection.io](https://changedetection.io/)はセルフホスト可能で、チェック時刻・通知・APIを備えます。5〜10分間隔なら公式発表から概ね5〜15分で検知できます。

3. **RSSHubは第3候補**  
   [RSSHub](https://github.com/DIYgod/RSSHub)はRSS化に便利ですが、公開デモはキャッシュや対象サイトのbot対策の影響を受けます。最速用途ではVPSにself-hostしても、対象側のHTML変更・403・429に依存します。  
   つまり、**「公式ページ差分監視の代わり」ではなく、実装を楽にするfallback**です。

## 投稿判定の実務ルール

- 即時の2本目を出す条件  
  - 公式発表で、新モデル・API・大規模OSS公開・重要ベンチマーク更新  
  - または、公式GitHub Release / Hugging Face公式組織の公開を確認できる  
  - さらにHN/Reddit/Xのいずれかで明確な技術者反応がある

- 日次投稿に回す条件  
  - Trending入り、スター増、論文、コミュニティ発のデモ  
  - 公式根拠が取れない噂・リーク・単一SNS投稿

- 最終的にDiscordへ残す項目  
  - 何が出たか  
  - まず試すURL  
  - 技術者が試したくなる理由を1文  
  - 一次ソースURL  
  - HN / GitHub / HFなどの補助シグナル

この構成なら、VPS上のPython定期実行とSQLiteだけで始められ、外部サービス費用は基本ゼロ、Xを加えても月数ドルに抑えられます。
---

## 抜き取り検査結果（2026-09-07・Fable検証）

主要フィードURLをcurlで実在確認した:

- ✅ OpenAI News RSS（200・正常なRSS）
- ✅ Google AI RSS（200・正常なRSS）
- ✅ TLDR AI / buttondown RSS（200・正常なRSS）
- ✅ Hacker News Firebase API（200・正常なJSON）
- ⚠️ **smol.ai AINews RSS は 402 Payment Required（DEPLOYMENT_DISABLED）で現在停止中**。
  sources.yaml採用時は本体サイトの差分監視か除外を検討すること

このファイルは調査時点のスナップショット。実装時（sources.yaml作成時）に各URLを再確認する。
