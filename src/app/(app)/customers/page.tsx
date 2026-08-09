import Link from "next/link";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { IconUsers, IconSearch } from "@/components/icons";
import { NewCustomerForm } from "./new-customer-form";

export default async function CustomersPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const { salon } = await requireCurrentSalon();
  const supabase = await createClient();

  let query = supabase
    .from("customers")
    .select("id, name, phone, birthday, created_at")
    .eq("salon_id", salon.id)
    .order("created_at", { ascending: false });

  if (q) {
    query = query.ilike("name", `%${q}%`);
  }

  const { data: customers } = await query;
  const list = customers ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="顧客・カルテ" subtitle={`登録数: ${list.length}名`} />

      <form method="get" className="relative max-w-xs">
        <IconSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
        <input
          type="text"
          name="q"
          defaultValue={q ?? ""}
          placeholder="名前で検索"
          className="w-full rounded-lg border border-stone-300 py-2 pl-9 pr-3 text-sm focus:border-rose-500 focus:outline-none focus:ring-1 focus:ring-rose-500"
        />
      </form>

      <NewCustomerForm />

      <Card className="overflow-hidden">
        {list.length === 0 ? (
          <EmptyState
            icon={<IconUsers className="h-10 w-10" />}
            title={q ? "該当する顧客が見つかりません" : "まだ顧客が登録されていません"}
            description={q ? undefined : "上の「新しい顧客を登録」から最初のお客様を追加しましょう"}
          />
        ) : (
          <>
            {/* Mobile: card list */}
            <ul className="divide-y divide-stone-100 sm:hidden">
              {list.map((customer) => (
                <li key={customer.id}>
                  <Link
                    href={`/customers/${customer.id}`}
                    className="flex items-center justify-between px-5 py-3 active:bg-stone-50"
                  >
                    <div>
                      <p className="text-sm font-medium text-stone-900">{customer.name}</p>
                      <p className="text-xs text-stone-500">{customer.phone ?? "電話番号未登録"}</p>
                    </div>
                    <p className="text-xs text-stone-400">{customer.birthday ?? ""}</p>
                  </Link>
                </li>
              ))}
            </ul>

            {/* Desktop: table */}
            <div className="hidden overflow-x-auto sm:block">
              <table className="w-full text-left text-sm">
                <thead className="bg-stone-50 text-xs font-medium uppercase text-stone-500">
                  <tr>
                    <th className="px-5 py-3">お名前</th>
                    <th className="px-5 py-3">電話番号</th>
                    <th className="px-5 py-3">誕生日</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-100">
                  {list.map((customer) => (
                    <tr key={customer.id} className="hover:bg-stone-50">
                      <td className="px-5 py-3">
                        <Link
                          href={`/customers/${customer.id}`}
                          className="font-medium text-stone-900 hover:text-rose-700 hover:underline"
                        >
                          {customer.name}
                        </Link>
                      </td>
                      <td className="px-5 py-3 text-stone-600">{customer.phone ?? "-"}</td>
                      <td className="px-5 py-3 text-stone-600">{customer.birthday ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
