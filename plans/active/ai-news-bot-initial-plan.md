# ai-news-bot 初期プラン（v2）

作成: 2026-09-07 ／ 状態: ドラフト（やなぎさんから運用詳細のヒアリング継続中）
v2: Codex sol クロスレビューの指摘を反映（詳細は末尾ログ）

## 目的

AUTOMATAのDiscordサーバーに、「技術者が手を動かしたくなる」AIニュースだけを厳選して
1日1回（超大型ニュース時のみ+1回）流すbotを作る。
やなぎさん（＋Fable）がベースを作り、うしくんさん（GitHub: USHIKUNDESUYO）が
KAGOYAクラウドVPSへデプロイする分業。クローン後は対話式セットアップで簡単に起動できること。

## 体制・環境（確定事項）

- リポジトリ: `Yanagi-1112/ai-news-bot`（public・作成済み）。コミット名義はグローバル既定（Yanagi-1112）
- コラボレータ: USHIKUNDESUYO（星野宇潮さん）を push 権限で招待済み
- デプロイ先: KAGOYAクラウドVPS（Ubuntu想定。うしくんさんが用意）
- 投稿先: AUTOMATAサーバーの1チャンネル（Discord Webhook）

## どんなbotか（設計方針）

### 配信ポリシー
- **基本1日1回の定時ダイジェスト**（例: 朝8:00 JST、.envで変更可）。トップ1本＋次点2〜4本
- **準速報の特例**: 収集は30分おき。LLMスコアが「超大型」しきい値を超えた項目のみ即時投稿、1日最大+1回（上限はコードで強制）
- 速報性のSLO: 「情報源で検知可能になってから原則45分以内に投稿」（収集間隔30分＋処理余裕。「最速」の言い換え）
- 0件の日は投稿しない（無理に埋めない）

### 選定基準（キュレーションの心臓部）
- LLMが候補を採点。基準は `prompts/curation.md`（日本語）に分離し、コードを触らず調整可能に
- ◎ 新モデル・新機能リリース（例: ChatGPT Astra、Gemini 3.8日本語切り出し、Fable 5.1）／ベンチマーク大幅更新／驚きのデモ（Astraの3D操作）／個人開発の面白い作例・話題のOSS
- ✗ 資金調達・人事・訴訟・規制などビジネス寄り／煽りだけで技術的中身がないもの
- few-shot例を含め、運用しながら追記して精度を上げる

### アーキテクチャ（Python・1プロセス・単一tick直列実行）
```
30分毎の単一tick: collector（情報源巡回）→ SQLite（既読・状態管理）→ curator（LLM採点・新着のみ）
  → poster（Webhook投稿: 定時ダイジェスト or 準速報）
```
- スケジューラ: APScheduler。`Asia/Tokyo` 固定・`max_instances=1`・`coalesce=True`・
  `misfire_grace_time` 設定。収集と投稿は同一tick内で直列（ジョブ競合を構造的に排除）
- SQLite: named volume に永続化。記事は `pending/sent/uncertain` の状態・配信種別・JST日付・
  payload hash・Discord message ID を保存。Webhookは `wait=true` で結果確認し、結果不明時は
  `uncertain` にして自動再送しない（重複より欠落を選ぶ）
- 重複排除: URL正規化＋タイトル類似。初回起動時は既存記事を「既読」として取り込み、過去記事を速報しない
- LLM: **v1は1プロバイダ・1モデルに固定**（差し替え抽象化はやらない）。モデルはやなぎさんの回答待ち
  （候補: claude-haiku-4-5 または deepseek-v4-flash）
- 有界化: 採点は新着のみ／1tickの候補数上限／日次トークン上限／source別timeout／部分失敗継続
  （1情報源が死んでも他は動く）／429は`Retry-After`尊重・上限付きbackoff
- 安全境界: 記事HTML取得はしない（登録済み情報源のRSS/APIフィールドのみ使う）。LLM出力はschema検証、
  投稿URLはcollectorが取得したものを使う（LLM生成URLを信用しない）。Discord投稿は常に
  `allowed_mentions: {"parse": []}`（@everyone等の通知事故防止）。タイトル・概要は長さ上限でtruncate

### 情報源（v1は規約が明確なものだけに限定）
- 公式ブログRSS（OpenAI / Anthropic / Google DeepMind / Meta / xAI / Mistral 等）
- 文書化された公式API: Hacker News（Algolia）・Hugging Face（trending）
- `sources.yaml` に情報源ごとの 規約URL・認証要否・レート制限・確認日 を台帳化
- Reddit・X・転載系アグリゲーターはv1スコープ外（規約・費用の確認後に拡張検討）
- 具体的なフィードURL一覧は codex-research の結果（research-news-sources.md）で確定 → 実装時にsources.yamlへ

### 秘密管理（publicリポジトリ前提・最重要）
- Webhook URL・APIキーは `.env` のみ。setup.shは**非表示入力**で受け取り、`chmod 600 .env`
- Dockerイメージに `.env` を焼き込まない（compose の env_file 参照のみ）。ログにキー・URLを出さない（マスク処理）
- リポジトリの secret scanning + push protection を有効化（作成済みリポジトリに設定）
- DEPLOY.md に漏洩時の再発行手順（Webhook削除→再発行、キーローテーション）を書く

### デプロイ体験（うしくんさん向け・Compose一本化）
- `git clone` → `./setup.sh`: ①docker存在チェック → ②Webhook URL・LLMキーを対話入力（非表示）で
  `.env` 生成 → ③`docker compose up -d` → ④`--send-test` で `[TEST]` 投稿の疎通確認
- CLIモードを3分離: `--dry-run`（外部送信・DB変更ゼロで整形結果を表示）／`--check-config`（設定検証のみ）／
  `--send-test`（確認付きで[TEST]投稿）
- 運用スクリプト: `./manage.sh status|logs|update|rollback`（updateは最新**リリースtag**へ、実行前にDBバックアップ）
- compose に healthcheck ＋ `restart: unless-stopped`
- systemd+venv手順は**やらない**（サポート面を1本に絞る）
- デプロイは main 最新ではなく**リリースtag指定**。mainはforce-push禁止ruleset（設定済みにする）
- リポジトリ直下にデプロイ特化 `AGENTS.md`（AIエージェントに「手順を聞いた」らそのまま誘導できる導線。public前提の内容のみ）
- README / DEPLOY.md は非エンジニアにも読める日本語。デモGIF/スクショ必須

## 合格基準（実装フェーズ完了の判定・4層）

1. **自動テスト（pytest・外部依存なし）**: fixture＋LLMスタブ＋mock clockで以下が全て通る —
   重複排除／速報しきい値と1日上限／JST日付境界での速報枠リセット／送信途中クラッシュ後に重複送信しない
   （poster呼出回数とDB状態を数値assert）／壊れたRSSで他情報源が継続／LLM不正JSONで安全側にスキップ／
   初回起動で過去記事を速報しない／候補0件で投稿しない／長文truncate
2. **live smoke（件数・費用上限付き）**: 実際の情報源＋実LLMで `--dry-run` がエラーなく完走し、
   ダイジェスト整形結果が標準出力に出る
3. **デプロイ再現**: クリーンなUbuntu環境（VMまたはコンテナ）で `./setup.sh` が対話入力だけで起動まで通り、
   コンテナ再作成後もSQLiteの既読が残っている（named volume確認）
4. **手動確認**: 自己所有テストチャンネルへの `--send-test`＋定時便の実配信E2Eで、フォーマットをやなぎさんが目視承認。
   直近1週間の実ニュースでdry-runし、拾うべきニュース（Astra・Gemini 3.8級）がトップに来るか確認
5. README（手順・構成図・デモ画像）完備、コミットにAI/Claudeクレジット無し、push前にoss-precheck相当の確認
6. リポジトリ設定: secret scanning＋push protection有効、mainのforce-push禁止rulesetあり

## やること（フェーズ分け）

### フェーズA: 今すぐ（このセッション・Fable直接）
- A1. プラン確定（セルフレビュー＋solクロスレビュー反映）✅
- A2. `gh auth switch -u Yanagi-1112` → publicリポジトリ作成 ✅
- A3. スケルトン初回コミット＆push ✅
- A4. USHIKUNDESUYO招待（push権限）✅
- A5. リポジトリ保護設定（secret scanning・push protection・force-push禁止ruleset）
- A6. やなぎさんに報告し、運用詳細（LLM・時刻・フォーマット・フック）を受け取る

### フェーズB: ベース実装（運用詳細確定後・codex-implement委譲）
- B1. collector + sources.yaml（リサーチ結果で確定した情報源台帳）
- B2. curator（curation.mdプロンプト・schema検証）+ poster（Webhook・allowed_mentions・状態管理）
- B3. setup.sh + manage.sh + Docker Compose（healthcheck・named volume）+ DEPLOY.md + AGENTS.md
- B4. pytest（合格基準1の全ケース）
- B5. E2E検証（テストWebhook実配信）→ README仕上げ（デモ画像）→ リリースtag `v0.1.0`

### フェーズC: 運用開始
- うしくんさんがKAGOYAへtag指定デプロイ → 本番Webhookに切替 → 数日運用して選定基準チューニング

## やらないこと（スコープ外）

- X/Twitter監視・Reddit・転載系アグリゲーター（規約/費用確認後の拡張候補）
- LLMプロバイダ差し替え抽象化（v1は1モデル固定）
- 双方向機能（コマンド応答等）・多チャンネル・多サーバー
- 記事全文の翻訳・全文要約（見出し＋2〜3行紹介＋リンクに留める）
- systemd+venvデプロイ経路（Compose一本）
- KAGOYA VPSの契約・初期設定（うしくんさん担当）

## 分担

- プラン・設計・レビュー・リポジトリ操作・E2E検証: Fable
- フェーズBのまとまった実装: codex-implement（implementer経由）
- 情報源調査: codex-research（実行中）
- デプロイ実作業: うしくんさん

## リスクと不可逆操作

- publicリポジトリ作成＋招待: やなぎさん明示依頼済み → 実行済み
- Discord実配信テストは自己所有テストチャンネルのみ。AUTOMATA本番へはうしくんさんデプロイ時まで流さない
- 秘密情報は上記「秘密管理」参照。push前に毎回秘密混入を確認

## 未解決の懸念（やなぎさんに確認する事項）

- LLMの既定モデルと予算感（Claude Haiku 4.5 か DeepSeek V4 Flash か）
- 定時投稿の時刻（朝8:00 JST仮置き）
- 投稿フォーマット（Embed有無・文体）
- 「フック次第で流す」に手動トリガーを含むか（自動しきい値のみで良いか）
- mainへのPR必須化までやるか（2人運用なので、v1はforce-push禁止＋tag運用のみに留める想定）

## セルフレビューログ

### 1周目（2026-09-07）
- 合格基準の機械判定可能性・要件解釈・git名義（Yanagi-1112切替）・不可逆操作の扱い・
  定番要件（READMEデモ画像/クレジット禁止/oss-precheck）を確認。AGENTS.md導線をスコープ追加

### Codex sol クロスレビュー（2026-09-07・採否）
- **採用（致命的4件）**: 秘密管理の強化（非表示入力・600・ログマスク・scanning/push protection・再発行手順）／
  SQLite永続化と送信状態設計（named volume・pending/sent/uncertain・wait=true）／
  スケジューラ仕様（Asia/Tokyo・単一tick直列・misfire方針）／デプロイの信頼境界（tag指定デプロイ・force-push禁止）
- **採用（高〜中）**: 情報源v1を公式RSS＋文書化API限定・規約台帳化／API・LLM費用の有界化／
  injection・mention事故対策／LLM 1プロバイダ固定／Compose一本化＋manage.sh／
  dry-run・check-config・send-testの3分離／合格基準の4層化＋異常系テスト追加／「最速」→45分SLO化
- **部分採用**: 「PR必須＋必須CI」→ 2人・小規模のためv1はforce-push禁止＋tagデプロイに縮小。
  PR運用は推奨に留め、必須化はやなぎさん判断に委ねる（未解決の懸念に記載）
- **不採用**: なし（実害ベースの指摘のみで、過剰品質の指摘は無かった）
