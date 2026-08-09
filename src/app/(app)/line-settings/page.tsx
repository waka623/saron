import { headers } from "next/headers";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { saveLineSettings } from "./actions";

export default async function LineSettingsPage() {
  const { salon } = await requireCurrentSalon();
  const headerList = await headers();
  const host = headerList.get("host");
  const protocol = host?.startsWith("localhost") ? "http" : "https";
  const webhookUrl = `${protocol}://${host}/api/line/webhook/${salon.id}`;

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-900">LINE連携設定</h1>
        <p className="mt-1 text-sm text-neutral-500">
          LINE公式アカウント（Messaging API）のチャネル情報を登録してください
        </p>
      </div>

      <div className="rounded-xl border border-neutral-200 bg-white p-5 text-sm shadow-sm">
        <p className="font-medium text-neutral-900">1. Webhook URLを設定</p>
        <p className="mt-1 text-neutral-500">
          LINE Developersコンソールの「Messaging API設定」→「Webhook URL」に以下を貼り付け、
          Webhookの利用を「オン」にしてください。
        </p>
        <p className="mt-3 break-all rounded-md bg-neutral-100 px-4 py-2 font-mono text-xs text-neutral-900">
          {webhookUrl}
        </p>
      </div>

      <form
        action={saveLineSettings}
        className="space-y-4 rounded-xl border border-neutral-200 bg-white p-5 shadow-sm"
      >
        <p className="text-sm font-medium text-neutral-900">2. チャネル情報を入力</p>
        <div>
          <label className="block text-sm font-medium text-neutral-700">チャネルID</label>
          <input
            name="channelId"
            defaultValue={salon.line_channel_id ?? ""}
            className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-neutral-700">
            チャネルシークレット
          </label>
          <input
            name="channelSecret"
            type="password"
            defaultValue={salon.line_channel_secret ?? ""}
            className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-neutral-700">
            チャネルアクセストークン（長期）
          </label>
          <input
            name="channelAccessToken"
            type="password"
            defaultValue={salon.line_channel_access_token ?? ""}
            className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800"
        >
          保存する
        </button>
      </form>

      <div className="rounded-xl border border-neutral-200 bg-white p-5 text-sm shadow-sm text-neutral-500">
        <p className="font-medium text-neutral-900">3. お客様とLINEアカウントを紐付ける</p>
        <p className="mt-1">
          各顧客の詳細ページに表示される「連携コード」を、友だち追加後のトーク画面で送信して
          もらうと自動的に連携されます。
        </p>
      </div>
    </div>
  );
}
