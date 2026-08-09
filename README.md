# サロンリピート

個人サロン向けの顧客カルテ管理 & LINEリピート促進SaaS。ホットペッパービューティーのような集客プラットフォームの代替ではなく、**既存顧客のリピート化**にコストと手間をかけずに取り組める補完ツールとして設計しています。

## できること（MVP）

- **顧客カルテ管理**: 顧客ごとの来店履歴・施術メモ・薬剤情報を記録
- **LINE連携**: サロンのLINE公式アカウントと顧客を紐付け（連携コード方式、LIFF不要）
- **リピート促進配信**: 誕生日クーポン／休眠顧客（○日未来店）への自動LINEメッセージ配信
- **ダッシュボード**: 登録顧客数・休眠顧客数などのサマリー

## 技術スタック

- Next.js 16 (App Router, Server Actions, Proxy)
- Supabase (Postgres, Auth, Row Level Security)
- LINE Messaging API
- Tailwind CSS 4

## セットアップ

### 1. Supabaseプロジェクトを作成

1. [supabase.com](https://supabase.com) でプロジェクトを作成
2. `supabase/migrations/0001_init.sql` の内容をSQL Editorで実行（テーブル作成 + RLSポリシー）
3. Project Settings → API から以下を取得

```bash
cp .env.local.example .env.local
```

`.env.local` に以下を設定:

```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
CRON_SECRET=（任意のランダム文字列）
```

### 2. 依存関係のインストール & 起動

```bash
npm install
npm run dev
```

[http://localhost:3000](http://localhost:3000) にアクセスすると `/dashboard` にリダイレクトされ（未ログインなら `/login`）、`/signup` からサロンアカウントを作成できます。

### 3. LINE公式アカウントを連携

1. [LINE Developers Console](https://developers.line.biz/) でMessaging APIチャネルを作成
2. ログイン後、管理画面の「LINE連携設定」ページにチャネルID・シークレット・長期アクセストークンを入力
3. 表示されたWebhook URLをLINE Developersの「Webhook URL」に設定し、Webhook利用をオンにする
4. 各顧客の詳細ページに表示される連携コードを、友だち追加後のトーク画面で送信してもらうとLINEアカウントが自動的に紐付く

### 4. 自動配信のスケジュール実行

`POST /api/campaigns/run`（`Authorization: Bearer $CRON_SECRET` ヘッダー必須）を1日1回呼び出すと、有効な配信ルールに該当する顧客へLINEメッセージが自動送信されます。Vercel CronやGitHub Actionsのscheduled workflowなど、外部スケジューラから叩く想定です。手動実行は「リピート促進配信」ページの「今すぐ配信を実行」ボタンからも可能です。

## ディレクトリ構成

```
src/
  app/
    (app)/          # ログイン後の画面（ダッシュボード・顧客・配信・LINE設定）
    login/ signup/  # 認証
    api/line/webhook/[salonId]/  # LINE Webhook受信
    api/campaigns/run/           # 配信バッチ実行エンドポイント
  lib/
    supabase/       # ブラウザ/サーバー/管理者用クライアント
    line/           # LINE Messaging API呼び出し・署名検証
    campaigns/      # 配信マッチング・送信ロジック
  types/database.ts # Supabaseテーブルの型定義
supabase/migrations/0001_init.sql  # DBスキーマ + RLS
```

## 今後の拡張候補

- Googleビジネスプロフィール連携（口コミ・予約導線）
- Instagram DM経由の予約受付
- 紹介プログラム（リファラルリンク・クーポン自動発行）
- カスタム配信（セグメント指定の一斉配信、現状はDBに保存のみで自動送信対象外）
- 予約管理機能そのものの追加（現状はカルテ・CRM・配信に特化）

## デプロイ

Vercelへのデプロイを想定しています。環境変数（`.env.local` と同じ内容）をVercelのプロジェクト設定に追加し、`vercel deploy` またはGitHub連携でデプロイしてください。
