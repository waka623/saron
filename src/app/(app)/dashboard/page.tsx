import Link from "next/link";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { IconUsers, IconCheckCircle, IconAlertTriangle, IconCalendarOff } from "@/components/icons";

const DORMANT_THRESHOLD_DAYS = 60;

export default async function DashboardPage() {
  const { salon } = await requireCurrentSalon();
  const supabase = await createClient();

  const [{ count: customerCount }, { data: recentVisits }, { data: visitDates }] =
    await Promise.all([
      supabase
        .from("customers")
        .select("id", { count: "exact", head: true })
        .eq("salon_id", salon.id),
      supabase
        .from("visit_records")
        .select("id, customer_id, visit_date, menu, customers(name)")
        .eq("salon_id", salon.id)
        .order("visit_date", { ascending: false })
        .limit(5),
      supabase
        .from("visit_records")
        .select("customer_id, visit_date")
        .eq("salon_id", salon.id)
        .order("visit_date", { ascending: false }),
    ]);

  const lastVisitByCustomer = new Map<string, string>();
  for (const row of visitDates ?? []) {
    if (!lastVisitByCustomer.has(row.customer_id)) {
      lastVisitByCustomer.set(row.customer_id, row.visit_date);
    }
  }

  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - DORMANT_THRESHOLD_DAYS);
  const dormantCount = [...lastVisitByCustomer.values()].filter(
    (date) => new Date(date) < cutoff
  ).length;

  const stats = [
    { label: "登録顧客数", value: customerCount ?? 0, icon: IconUsers },
    { label: "来店実績あり", value: lastVisitByCustomer.size, icon: IconCheckCircle },
    {
      label: `${DORMANT_THRESHOLD_DAYS}日以上未来店`,
      value: dormantCount,
      icon: IconAlertTriangle,
      highlight: dormantCount > 0,
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-stone-900">ダッシュボード</h1>
        <p className="mt-1 text-sm text-stone-500">{salon.name} の状況</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <Card key={stat.label} className="p-5">
              <div className="flex items-center justify-between">
                <p className="text-sm text-stone-500">{stat.label}</p>
                <Icon
                  className={`h-4.5 w-4.5 ${stat.highlight ? "text-amber-500" : "text-stone-300"}`}
                />
              </div>
              <p
                className={`mt-2 text-3xl font-semibold ${
                  stat.highlight ? "text-amber-600" : "text-stone-900"
                }`}
              >
                {stat.value}
                <span className="ml-1 text-base font-normal text-stone-400">名</span>
              </p>
            </Card>
          );
        })}
      </div>

      {dormantCount > 0 && (
        <Card className="flex items-start gap-3 border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <IconAlertTriangle className="h-5 w-5 shrink-0" />
          <p>
            {dormantCount}名のお客様が{DORMANT_THRESHOLD_DAYS}日以上来店していません。
            <Link href="/campaigns" className="ml-1 font-medium underline underline-offset-2">
              リピート促進配信を設定する
            </Link>
          </p>
        </Card>
      )}

      <Card>
        <CardHeader title="最近の来店記録" />
        {(recentVisits ?? []).length === 0 ? (
          <EmptyState
            icon={<IconCalendarOff className="h-9 w-9" />}
            title="まだ来店記録がありません"
            description="顧客ページから来店記録を追加すると、ここに表示されます"
          />
        ) : (
          <ul className="divide-y divide-stone-100">
            {(recentVisits ?? []).map((visit) => (
              <li key={visit.id} className="flex items-center justify-between px-5 py-3">
                <div>
                  <p className="text-sm font-medium text-stone-900">
                    {(visit.customers as unknown as { name: string } | null)?.name ?? "不明"}
                  </p>
                  <p className="text-xs text-stone-500">{visit.menu ?? "メニュー未記入"}</p>
                </div>
                <p className="text-xs text-stone-400">{visit.visit_date}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
