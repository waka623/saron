# SNS運用 PDCAエージェント（週次レポート素案生成）

Google Apps Script (GAS) 上で動く、SNS運用の週次データ集計＋検証レポート素案の自動生成エージェント。
PDCAのうち **C（検証）とA（改善示唆）** を担う。詳細な背景・設計思想は依頼元の要件定義書を参照。

## 役割境界（最重要）

「データが相手の仕事はエージェント、人が相手の仕事は人」。

- ✅ やる: トラッカー集計、前週比KPI算出、AARRRファネル分析、示唆の叩き台生成、レポート素案の書き出し
- ❌ やらない: レポートの自動送信、クライアント対応、示唆の採用判断

`runWeeklyReport()` はレポート素案を Google Docs（またはSheet）に書き出すところで必ず止まる。
そこから先（表現の微調整・最終仕上げ・送信）は人が行う。

## ⚠️ 実装時に必ず確認すること: トラッカーの列構成

要件定義書の時点でトラッカーの実列構成は **未確定(TBD)** だった。`Config.gs` の `CONFIG.COLUMNS` は
要件定義書3節の「想定される項目例」に基づく **仮設定**。実物のトラッカーを見てヘッダー名が違う場合は
`Config.gs` の値だけを書き換えれば動く（集計・プロンプト生成のロジック側はヘッダー名を直接参照しない設計）。

```js
COLUMNS: {
  DATE: '日付',
  ACCOUNT: 'アカウント',        // 複数アカウント運用しないなら '' にしてOK
  FOLLOWERS: 'フォロワー数',
  REACH: 'リーチ',
  IMPRESSIONS: 'インプレッション',
  LIKES: 'いいね',
  SAVES: '保存',
  COMMENTS: 'コメント',
  SHARES: 'シェア',
  PROFILE_ACCESS: 'プロフィールアクセス',
  POST_TYPE: '投稿種別',
},
```

トラッカーは「1行 = 1日（アカウント列がある場合は1日×1アカウント）」の縦持ち形式を想定している。
投稿単位のログではなく日次スナップショットである前提で、フォロワー数は週内の最終値と週初値の差分（純増数）を
Retentionの指標として使っている。

## セットアップ

1. [Google Apps Script](https://script.google.com/) で新規プロジェクトを作成
2. このディレクトリの `*.gs` ファイルの中身をそれぞれ同名のスクリプトファイルとしてコピー
   （`clasp` を使える場合は `clasp push` でそのままデプロイ可能）
3. 「プロジェクトの設定」→「スクリプト プロパティ」に以下を追加
   - `TRACKER_SPREADSHEET_ID`: 運用トラッカーのスプレッドシートID
   - `CLAUDE_API_KEY`: Anthropic APIキー（コードには直書きしない）
4. `Config.gs` の `COLUMNS` を実物のトラッカーのヘッダーに合わせて調整
5. Apps Scriptエディタで `debugAggregationOnly` を手動実行し、集計結果（ログ）が意図通りか確認
6. `debugPromptOnly` を手動実行し、Claudeに渡すプロンプトの中身を確認
7. `runWeeklyReport` を手動実行し、Google Docsにレポート素案が生成されることを確認（この段階では自動送信されない点を再確認）
8. 問題なければ `setupWeeklyTrigger` を一度だけ実行し、毎週月曜9時台の自動実行を有効化

トリガーを止めたい／設定し直したい場合は `removeWeeklyTrigger` を実行する。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `Config.gs` | スクリプトプロパティ、列マッピング、出力先などの設定 |
| `Utils.gs` | 日付/数値パース、数値フォーマットなどの共通処理 |
| `SheetReader.gs` | トラッカーシートの読み込み・正規化 |
| `Aggregator.gs` | 週次集計・前週比KPI・AARRRファネル分析 |
| `ClaudePrompt.gs` | Claudeへの示唆生成プロンプト組み立て（チューニング対象） |
| `ClaudeClient.gs` | Claude API (`UrlFetchApp`) 呼び出し |
| `ReportWriter.gs` | レポート素案の組み立て・Google Docs/Sheetsへの書き出し |
| `Main.gs` | `runWeeklyReport()` 本体、手動検証用関数 |
| `Triggers.gs` | 週次トリガーの設定/解除 |
| `appsscript.json` | GASマニフェスト（タイムゾーン・権限スコープ） |

## AARRRの割り当て（初期仮説）

トラッカーに売上列が無い前提のため、Revenueはデータ不足として扱い「対象外」表示になる
（将来、売上/成約データが取れるようになったら `Aggregator.gs` の `AARRR_STAGES_` にmetricsを追加する）。

| 段階 | 使用指標 |
|---|---|
| Acquisition | リーチ、インプレッション |
| Activation | プロフィールアクセス、エンゲージメント率 |
| Retention | フォロワー純増数（週初→週末） |
| Referral | シェア数 |
| Revenue | （データなし。将来拡張） |

各段階は前週比の増減率が `+5%`超で「好調」、`-5%`未満で「要注意」、それ以外は「横ばい」と判定する
（閾値は `Aggregator.gs` の `STATUS_UP_THRESHOLD_` / `STATUS_DOWN_THRESHOLD_`）。

## 複数アカウント・横展開について

`COLUMNS.ACCOUNT` を設定すればトラッカー内の複数アカウントを自動判別して個別にレポートを生成する
（`CONFIG.TARGET_ACCOUNTS` で対象を絞り込みも可能）。他クライアントへ横展開する場合は、
クライアントごとに `TRACKER_SPREADSHEET_ID` の異なるGASプロジェクトを複製し、`Config.gs` の
`COLUMNS` を実物トラッカーに合わせて調整するだけで移植できる想定。
