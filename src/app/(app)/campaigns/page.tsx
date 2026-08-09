import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { createCampaign, toggleCampaign, runCampaignsNow } from "./actions";

const TYPE_LABELS: Record<string, string> = {
  birthday: "誕生日クーポン",
  no_visit_reminder: "休眠顧客リマインド",
  custom: "カスタム（手動送信予定）",
};

export default async function CampaignsPage() {
  const { salon } = await requireCurrentSalon();
  const supabase = await createClient();

  const { data: campaigns } = await supabase
    .from("campaigns")
    .select("*")
    .eq("salon_id", salon.id)
    .order("created_at", { ascending: false });

  const { data: logs } = await supabase
    .from("campaign_logs")
    .select("id, status, sent_at, error_message, customers(name), campaigns(name)")
    .in("campaign_id", (campaigns ?? []).map((c) => c.id))
    .order("sent_at", { ascending: false })
    .limit(10);

  const lineConnected = Boolean(salon.line_channel_access_token);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">リピート促進配信</h1>
          <p className="mt-1 text-sm text-neutral-500">
            誕生日・休眠顧客への自動LINE配信を設定します
          </p>
        </div>
        <form action={runCampaignsNow}>
          <button
            type="submit"
            disabled={!lineConnected}
            className="rounded-md border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            今すぐ配信を実行
          </button>
        </form>
      </div>

      {!lineConnected && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          LINE連携が未設定のため配信できません。LINE連携設定ページでチャネル情報を登録してください。
        </div>
      )}

      <details className="rounded-xl border border-neutral-200 bg-white shadow-sm">
        <summary className="cursor-pointer select-none px-5 py-4 text-sm font-semibold text-neutral-900">
          + 新しい配信ルールを作成
        </summary>
        <form
          action={createCampaign}
          className="space-y-4 border-t border-neutral-100 px-5 py-4"
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-neutral-700">配信名</label>
              <input
                name="name"
                required
                placeholder="お誕生日クーポン"
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700">種類</label>
              <select
                name="type"
                required
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
              >
                <option value="birthday">誕生日クーポン</option>
                <option value="no_visit_reminder">休眠顧客リマインド</option>
                <option value="custom">カスタム（手動送信予定）</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700">
                未来店日数（休眠リマインド用）
              </label>
              <input
                name="daysSinceLastVisit"
                type="number"
                min={1}
                placeholder="60"
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-neutral-700">
              メッセージ本文（{"{{name}}"} でお客様名を挿入できます）
            </label>
            <textarea
              name="messageTemplate"
              required
              rows={3}
              placeholder={"{{name}}様、お誕生日おめでとうございます！次回ご来店時に使える500円クーポンをプレゼント🎁"}
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800"
          >
            作成する
          </button>
        </form>
      </details>

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-50 text-xs font-medium uppercase text-neutral-500">
            <tr>
              <th className="px-5 py-3">配信名</th>
              <th className="px-5 py-3">種類</th>
              <th className="px-5 py-3">状態</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            {(campaigns ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-5 py-6 text-center text-neutral-400">
                  配信ルールがまだありません
                </td>
              </tr>
            )}
            {(campaigns ?? []).map((campaign) => (
              <tr key={campaign.id}>
                <td className="px-5 py-3 font-medium text-neutral-900">{campaign.name}</td>
                <td className="px-5 py-3 text-neutral-600">
                  {TYPE_LABELS[campaign.type]}
                  {campaign.type === "no_visit_reminder" &&
                    campaign.days_since_last_visit &&
                    `（${campaign.days_since_last_visit}日）`}
                </td>
                <td className="px-5 py-3">
                  <span
                    className={`rounded-full px-2 py-1 text-xs font-medium ${
                      campaign.is_active
                        ? "bg-green-100 text-green-700"
                        : "bg-neutral-100 text-neutral-500"
                    }`}
                  >
                    {campaign.is_active ? "有効" : "停止中"}
                  </span>
                </td>
                <td className="px-5 py-3 text-right">
                  <form action={toggleCampaign.bind(null, campaign.id, !campaign.is_active)}>
                    <button
                      type="submit"
                      className="text-xs font-medium text-neutral-500 hover:underline"
                    >
                      {campaign.is_active ? "停止する" : "再開する"}
                    </button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl border border-neutral-200 bg-white shadow-sm">
        <div className="border-b border-neutral-200 px-5 py-4">
          <h2 className="text-sm font-semibold text-neutral-900">配信履歴</h2>
        </div>
        <ul className="divide-y divide-neutral-100">
          {(logs ?? []).length === 0 && (
            <li className="px-5 py-6 text-sm text-neutral-400">配信履歴がありません</li>
          )}
          {(logs ?? []).map((log) => (
            <li key={log.id} className="flex items-center justify-between px-5 py-3 text-sm">
              <div>
                <span className="font-medium text-neutral-900">
                  {(log.customers as unknown as { name: string } | null)?.name ?? "不明"}
                </span>
                <span className="ml-2 text-neutral-500">
                  {(log.campaigns as unknown as { name: string } | null)?.name}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={`text-xs font-medium ${
                    log.status === "sent"
                      ? "text-green-600"
                      : log.status === "failed"
                        ? "text-red-600"
                        : "text-neutral-400"
                  }`}
                >
                  {log.status}
                </span>
                <span className="text-xs text-neutral-400">
                  {new Date(log.sent_at).toLocaleString("ja-JP")}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
