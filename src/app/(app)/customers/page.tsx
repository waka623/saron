import Link from "next/link";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { createCustomer } from "./actions";

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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">顧客・カルテ</h1>
          <p className="mt-1 text-sm text-neutral-500">
            登録数: {customers?.length ?? 0}名
          </p>
        </div>
      </div>

      <form method="get" className="flex gap-2">
        <input
          type="text"
          name="q"
          defaultValue={q ?? ""}
          placeholder="名前で検索"
          className="w-64 rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-md border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-100"
        >
          検索
        </button>
      </form>

      <details className="rounded-xl border border-neutral-200 bg-white shadow-sm">
        <summary className="cursor-pointer select-none px-5 py-4 text-sm font-semibold text-neutral-900">
          + 新しい顧客を登録
        </summary>
        <form action={createCustomer} className="space-y-4 border-t border-neutral-100 px-5 py-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-neutral-700">お名前</label>
              <input
                name="name"
                required
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700">電話番号</label>
              <input
                name="phone"
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700">誕生日</label>
              <input
                name="birthday"
                type="date"
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-neutral-700">
              メモ（アレルギー、要望など）
            </label>
            <textarea
              name="notes"
              rows={2}
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800"
          >
            登録する
          </button>
        </form>
      </details>

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-50 text-xs font-medium uppercase text-neutral-500">
            <tr>
              <th className="px-5 py-3">お名前</th>
              <th className="px-5 py-3">電話番号</th>
              <th className="px-5 py-3">誕生日</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            {(customers ?? []).length === 0 && (
              <tr>
                <td colSpan={3} className="px-5 py-6 text-center text-neutral-400">
                  顧客が登録されていません
                </td>
              </tr>
            )}
            {(customers ?? []).map((customer) => (
              <tr key={customer.id} className="hover:bg-neutral-50">
                <td className="px-5 py-3">
                  <Link
                    href={`/customers/${customer.id}`}
                    className="font-medium text-neutral-900 hover:underline"
                  >
                    {customer.name}
                  </Link>
                </td>
                <td className="px-5 py-3 text-neutral-600">{customer.phone ?? "-"}</td>
                <td className="px-5 py-3 text-neutral-600">{customer.birthday ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
