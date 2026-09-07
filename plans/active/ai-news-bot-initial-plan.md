# ai-news-bot 初期プラン（v1）

作成: 2026-09-07 ／ 状態: ドラフト（やなぎさんから運用詳細のヒアリング継続中）

## 目的

AUTOMATAのDiscordサーバーに、「技術者が手を動かしたくなる」AIニュースだけを厳選して
1日1回（超大型ニュース時のみ+1回）最速で流すbotを作る。
やなぎさん（＋Fable）がベースを作り、うしくんさん（GitHub: USHIKUNDESUYO）が
KAGOYAクラウドVPSへデプロイする分業。クローン後は対話式セットアップで簡単に起動できること。

## 体制・環境（確定事項）

- リポジトリ: `Yanagi-1112/ai-news-bot`（public）。コミット名義はグローバル既定（Yanagi-1112）
- コラボレータ: USHIKUNDESUYO を招待（push権限）
- デプロイ先: KAGOYAクラウドVPS（OSはUbuntu想定。うしくんさんが用意）
- 投稿先: AUTOMATAサーバーの1チャンネル

## どんなbotか（設計方針）

### 配信ポリシー
- **基本1日1回の定時ダイジェスト**（例: 朝8:00 JST、時刻は.envで変更可）。トップ1本＋次点2〜4本の構成
- **速報の特例**: 収集は30分おきに回し、LLMスコアが「超大型」しきい値を超えた項目だけ即時投稿。1日の追加投稿は最大1回（スパム防止のレートリミットをコード側で強制）
- 1チャンネルに大量に流さない。「少なすぎず多すぎず」は定時1回+特例で担保

### 選定基準（キュレーションの心臓部）
- LLMに候補ニュースを採点させる。基準はプロンプトファイル `prompts/curation.md` に日本語で記述し、コードと分離（非エンジニアでも調整可能に）
- 基準の言語化: 「自分でも実装してみたい」「触ってみたい」と思えるか
  - ◎ 新モデル・新機能リリース（例: ChatGPT Astra、Gemini 3.8の日本語切り出し、Fable 5.1）
  - ◎ ベンチマーク大幅更新、驚きのデモ（例: Astraの3Dモデル操作）
  - ◎ 個人開発者の面白い作例・話題のOSS
  - ✗ 資金調達・人事・訴訟・規制などビジネス寄りニュース
  - ✗ 煽りだけで技術的中身がないもの
- few-shot例をプロンプトに含め、運用しながら追記して精度を上げる

### アーキテクチャ（Python・シンプル構成）
```
collector（情報源巡回・30分毎） → SQLite（既読管理・候補プール） → curator（LLM採点）
  → poster（Discord Webhook投稿: 定時ダイジェスト or 速報）
```
- **Discord投稿はWebhook方式**（bot常駐・Gateway接続なし）。一方向投稿にはこれが最も単純で、
  デプロイも「WebhookのURLを1本発行して.envに貼るだけ」になる
- スケジューラはプロセス内蔵（APScheduler等）で1プロセス完結。cron依存を作らない
- 重複排除: URL正規化＋タイトル類似で既読管理（SQLite）
- LLM: OpenAI互換クライアントで抽象化し、モデル・キーは.envで差し替え可能に
  （既定候補: 精度優先なら claude-haiku-4-5 / コスト優先なら deepseek-v4-flash。既定はやなぎさんに確認）

### 情報源（codex-research調査結果を反映して確定）
- 公式ブログRSS（OpenAI / Anthropic / Google DeepMind / Meta / xAI / Mistral 等）
- Hacker News（Algolia API・スコアしきい値付き）
- Hugging Face trending（models/papers API）
- Reddit（r/LocalLLaMA 等のRSS、無料範囲）
- AIニュースアグリゲーター（smol.ai news 等、調査結果次第）
- X監視は初期スコープ外（API費用が高い。twitterapi.io流用は運用費が決まってから検討）
- 情報源リストは `sources.yaml` に分離し、追加・削除をコード変更なしでできるようにする

### デプロイ体験（うしくんさん向け・最重要要件）
- `git clone` → `./setup.sh` の対話式セットアップで完結させる:
  1. 必要コマンド（docker等）の存在チェック
  2. Webhook URL・LLMキーを対話で聞いて `.env` を生成
  3. `docker compose up -d` で起動、テスト投稿（--dry-run）で疎通確認
- **Docker Compose を第一候補**（KAGOYA VPSのUbuntuで動く。環境差を吸収）。
  docker無し環境向けに systemd + venv の手順も DEPLOY.md に併記
- README / DEPLOY.md は非エンジニアにも読める日本語で。デモGIF/スクショ必須（README必須要件）
- リポジトリ直下にデプロイ手順特化の `AGENTS.md`（クローン後にAIエージェントへ「手順を聞いたら」
  そのまま誘導・自動実行できる導線）を置く。個人情報・内部事情は書かない（public前提の内容に限定）

## 合格基準（実装フェーズ完了の判定。機械的に検証できる形）

1. `./setup.sh` を新規環境（ローカルのクリーンなDockerコンテナで模擬）で実行し、対話入力だけで `.env` 生成〜起動まで通る
2. `python -m bot.main --dry-run` で、実際の情報源から収集→採点→ダイジェスト整形までがエラーなく走り、投稿内容が標準出力に出る
3. 自己所有のテスト用Discordチャンネルへの実配信E2Eで、ダイジェストが意図したフォーマットで届く（スクショで確認）
4. 同じ記事を2回目の収集で重複投稿しない（SQLiteの既読管理が効いていることをログで確認）
5. 速報しきい値・1日の投稿上限がテストで検証されている（pytest通過）
6. READMEにセットアップ手順・構成図・デモ画像があり、コミットにAI/Claudeクレジットが無い
7. リポジトリがpublicで存在し、USHIKUNDESUYOがコラボレータ（招待済み）である

## やること（フェーズ分け）

### フェーズA: 今すぐ（このセッション・Fable直接）
- A1. このプランを確定（セルフレビュー＋Codex solクロスレビュー）
- A2. `gh auth switch -u Yanagi-1112` → public リポジトリ `ai-news-bot` 作成
- A3. スケルトン（README初版・.gitignore・LICENSE(MIT)・plans/）を初回コミット＆push
- A4. USHIKUNDESUYO をコラボレータ招待（push権限）
- A5. やなぎさんに報告し、運用詳細（投稿チャンネル、LLM予算、定時時刻など）を受け取る

### フェーズB: ベース実装（運用詳細確定後・codex-implement委譲）
- B1. collector + sources.yaml（情報源はリサーチ結果で確定）
- B2. curator（LLM採点・curation.mdプロンプト）+ poster（Webhook・ダイジェスト整形）
- B3. setup.sh + Docker Compose + DEPLOY.md
- B4. pytest（重複排除・レートリミット・整形）
- B5. E2E検証（テストWebhookで実配信）→ README仕上げ（デモ画像）

### フェーズC: 運用開始
- うしくんさんがKAGOYAへデプロイ → 本番Webhookに切替 → 数日運用して選定基準をチューニング

## やらないこと（スコープ外）

- X/Twitter有料APIでの監視（費用確定まで）
- 双方向機能（コマンド応答・リアクション集計など）。投稿専用に絞る
- 多チャンネル配信・多サーバー対応
- 記事全文の自動翻訳・全文要約の配信（見出し＋2〜3行の紹介＋リンクに留める）
- KAGOYA VPSの契約・初期設定そのもの（うしくんさんの担当領域）

## 分担

- プラン・設計・レビュー・リポジトリ操作・E2E検証: Fable
- フェーズBのまとまった実装: codex-implement（implementerサブエージェント経由）
- 情報源調査: codex-research（実行中）
- デプロイ実作業: うしくんさん

## リスクと不可逆操作

- **publicリポジトリ作成＋コラボレータ招待**: 外部公開・外部送信に当たるが、今回やなぎさんが明示依頼済み → 実行してよい
- 招待相手のID `USHIKUNDESUYO` はGitHub上の実在確認をしてから招待する（打ち間違い招待の防止）
- Discordへの実配信テストは自己所有テストチャンネルで行い、AUTOMATA本番チャンネルへは
  うしくんさんデプロイ時まで流さない
- APIキー・Webhook URLは.envのみに置き、リポジトリはpublicなので.gitignore徹底＋push前にoss-precheck相当の確認

## 検証方法

- 合格基準1〜5を実装フェーズ完了時に順に実行（dry-run→テストチャンネルE2E→pytest）
- 選定品質は、直近1週間の実ニュースでdry-runし、拾うべきだったニュース（Astra・Gemini 3.8等の類例）が
  トップに来るかをやなぎさんと目視レビュー

## 未解決の懸念（やなぎさんに確認する事項）

- LLMの既定モデルと予算感（Claude API か DeepSeek か）
- 定時投稿の時刻
- 投稿フォーマットの好み（Embed使用有無・文体）
- 「フック次第で流す」のフックに外部トリガー（手動コマンド等）を想定しているか

## セルフレビューログ

### 1周目（2026-09-07）
- 合格基準7個はすべて機械判定可能（dry-run出力・pytest・スクショ・gh APIでの状態確認）→OK
- 「クローンしたら手順を聞いたら自動で簡単に」の解釈: setup.shだけでなく、AIエージェントに
  聞いても誘導できるよう deploy特化AGENTS.md をスコープに追加（本文修正済み）
- 「ボット」という依頼語に対しWebhook方式（常駐Gateway無し）を選択した点は設計判断として明示。
  見た目はbot投稿と同等で、デプロイ簡単化の要件を優先。速報の即時性はcollectorの30分ポーリングで担保
- git名義: gh activeが現在Keisuke-Someyaのため、A2で必ず `gh auth switch -u Yanagi-1112` を先行
  （feedback_git_identity準拠）。コミットauthorはグローバル既定のYanagi-1112でOK
- 不可逆操作（public作成・招待）はやなぎさん明示依頼のため確認不要。招待前にユーザー実在確認を追加済み
- 定番要件チェック: READMEデモ画像○ / AIクレジット禁止○ / oss-precheck相当の秘密情報確認○
- より小さい切り方: フェーズA（リポジトリのみ）とB（実装）を分離済み。Bも運用詳細待ちで着手しない
