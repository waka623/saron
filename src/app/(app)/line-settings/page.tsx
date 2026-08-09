import { headers } from "next/headers";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { LineSettingsForm } from "./line-settings-form";

export default async function LineSettingsPage() {
  const { salon } = await requireCurrentSalon();
  const headerList = await headers();
  const host = headerList.get("host");
  const protocol = host?.startsWith("localhost") ? "http" : "https";
  const webhookUrl = `${protocol}://${host}/api/line/webhook/${salon.id}`;

  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader
        title="LINE連携設定"
        subtitle="LINE公式アカウント（Messaging API）のチャネル情報を登録してください"
      />

      <Card className="p-5 text-sm">
        <p className="flex items-center gap-2 font-medium text-stone-900">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-rose-100 text-xs text-rose-700">
            1
          </span>
          Webhook URLを設定
        </p>
        <p className="mt-2 text-stone-500">
          LINE Developersコンソールの「Messaging API設定」→「Webhook URL」に以下を貼り付け、
          Webhookの利用を「オン」にしてください。
        </p>
        <p className="mt-3 break-all rounded-lg bg-stone-100 px-4 py-2 font-mono text-xs text-stone-900">
          {webhookUrl}
        </p>
      </Card>

      <Card className="p-5">
        <p className="mb-4 flex items-center gap-2 text-sm font-medium text-stone-900">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-rose-100 text-xs text-rose-700">
            2
          </span>
          チャネル情報を入力
        </p>
        <LineSettingsForm
          channelId={salon.line_channel_id}
          channelSecret={salon.line_channel_secret}
          channelAccessToken={salon.line_channel_access_token}
        />
      </Card>

      <Card className="p-5 text-sm text-stone-500">
        <p className="flex items-center gap-2 font-medium text-stone-900">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-rose-100 text-xs text-rose-700">
            3
          </span>
          お客様とLINEアカウントを紐付ける
        </p>
        <p className="mt-2">
          各顧客の詳細ページに表示される「連携コード」を、友だち追加後のトーク画面で送信して
          もらうと自動的に連携されます。
        </p>
      </Card>
    </div>
  );
}
