import Link from "next/link";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";

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
    { label: "登録顧客数", value: customerCount ?? 0 },
    { label: "来店実績あり", value: lastVisitByCustomer.size },
    { label: `${DORMANT_THRESHOLD_DAYS}日以上未来店`, value: dormantCount, highlight: dormantCount > 0 },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-900">ダッシュボード</h1>
        <p className="mt-1 text-sm text-neutral-500">{salon.name} の状況</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="rounded-xl border border-neutral-200 bg-white p-5 shadow-sm"
          >
            <p className="text-sm text-neutral-500">{stat.label}</p>
            <p
              className={`mt-2 text-3xl font-semibold ${
                stat.highlight ? "text-amber-600" : "text-neutral-900"
              }`}
            >
              {stat.value}
              <span className="ml-1 text-base font-normal text-neutral-400">名</span>
            </p>
          </div>
        ))}
      </div>

      {dormantCount > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          {dormantCount}名のお客様が{DORMANT_THRESHOLD_DAYS}日以上来店していません。
          <Link href="/campaigns" className="ml-1 font-medium underline">
            リピート促進配信を設定する
          </Link>
        </div>
      )}

      <div className="rounded-xl border border-neutral-200 bg-white shadow-sm">
        <div className="border-b border-neutral-200 px-5 py-4">
          <h2 className="text-sm font-semibold text-neutral-900">最近の来店記録</h2>
        </div>
        <ul className="divide-y divide-neutral-100">
          {(recentVisits ?? []).length === 0 && (
            <li className="px-5 py-6 text-sm text-neutral-400">
              まだ来店記録がありません
            </li>
          )}
          {(recentVisits ?? []).map((visit) => (
            <li key={visit.id} className="flex items-center justify-between px-5 py-3">
              <div>
                <p className="text-sm font-medium text-neutral-900">
                  {(visit.customers as unknown as { name: string } | null)?.name ?? "不明"}
                </p>
                <p className="text-xs text-neutral-500">{visit.menu ?? "メニュー未記入"}</p>
              </div>
              <p className="text-xs text-neutral-400">{visit.visit_date}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
