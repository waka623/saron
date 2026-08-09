import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { IconMegaphone, IconAlertTriangle } from "@/components/icons";
import { NewCampaignForm } from "./new-campaign-form";
import { RunNowButton } from "./run-now-button";
import { CampaignToggleButton } from "./campaign-toggle-button";

const TYPE_LABELS: Record<string, string> = {
  birthday: "誕生日クーポン",
  no_visit_reminder: "休眠顧客リマインド",
  custom: "カスタム（手動送信予定）",
};

const LOG_STATUS: Record<string, { label: string; tone: "success" | "danger" | "neutral" }> = {
  sent: { label: "送信済み", tone: "success" },
  failed: { label: "失敗", tone: "danger" },
  skipped: { label: "スキップ", tone: "neutral" },
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
    <div className="space-y-6">
      <PageHeader
        title="リピート促進配信"
        subtitle="誕生日・休眠顧客への自動LINE配信を設定します"
        action={<RunNowButton disabled={!lineConnected} />}
      />

      {!lineConnected && (
        <Card className="flex items-start gap-3 border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <IconAlertTriangle className="h-5 w-5 shrink-0" />
          <span>
            LINE連携が未設定のため配信できません。LINE連携設定ページでチャネル情報を登録してください。
          </span>
        </Card>
      )}

      <NewCampaignForm />

      <Card className="overflow-hidden">
        {(campaigns ?? []).length === 0 ? (
          <EmptyState
            icon={<IconMegaphone className="h-9 w-9" />}
            title="配信ルールがまだありません"
            description="上の「新しい配信ルールを作成」から設定を始めましょう"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-stone-50 text-xs font-medium uppercase text-stone-500">
                <tr>
                  <th className="px-5 py-3">配信名</th>
                  <th className="px-5 py-3">種類</th>
                  <th className="px-5 py-3">状態</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {(campaigns ?? []).map((campaign) => (
                  <tr key={campaign.id}>
                    <td className="px-5 py-3 font-medium text-stone-900">{campaign.name}</td>
                    <td className="px-5 py-3 text-stone-600">
                      {TYPE_LABELS[campaign.type]}
                      {campaign.type === "no_visit_reminder" &&
                        campaign.days_since_last_visit &&
                        `（${campaign.days_since_last_visit}日）`}
                    </td>
                    <td className="px-5 py-3">
                      <Badge tone={campaign.is_active ? "success" : "neutral"}>
                        {campaign.is_active ? "有効" : "停止中"}
                      </Badge>
                    </td>
                    <td className="px-5 py-3 text-right">
                      <CampaignToggleButton campaignId={campaign.id} isActive={campaign.is_active} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="配信履歴" />
        {(logs ?? []).length === 0 ? (
          <EmptyState title="配信履歴がありません" />
        ) : (
          <ul className="divide-y divide-stone-100">
            {(logs ?? []).map((log) => {
              const statusInfo = LOG_STATUS[log.status] ?? { label: log.status, tone: "neutral" as const };
              return (
                <li key={log.id} className="flex items-center justify-between px-5 py-3 text-sm">
                  <div>
                    <span className="font-medium text-stone-900">
                      {(log.customers as unknown as { name: string } | null)?.name ?? "不明"}
                    </span>
                    <span className="ml-2 text-stone-500">
                      {(log.campaigns as unknown as { name: string } | null)?.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge tone={statusInfo.tone}>{statusInfo.label}</Badge>
                    <span className="text-xs text-stone-400">
                      {new Date(log.sent_at).toLocaleString("ja-JP")}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
