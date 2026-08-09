import { notFound } from "next/navigation";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { addVisitRecord } from "../actions";

export default async function CustomerDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const { salon } = await requireCurrentSalon();
  const supabase = await createClient();

  const { data: customer } = await supabase
    .from("customers")
    .select("*")
    .eq("id", id)
    .eq("salon_id", salon.id)
    .single();

  if (!customer) {
    notFound();
  }

  const { data: visits } = await supabase
    .from("visit_records")
    .select("id, visit_date, menu, memo, staff:staff_id(name)")
    .eq("customer_id", id)
    .order("visit_date", { ascending: false });

  const linkingCode = customer.line_link_token.slice(0, 8).toUpperCase();

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neutral-900">{customer.name}</h1>
          <p className="mt-1 text-sm text-neutral-500">
            {customer.phone ?? "電話番号未登録"}
            {customer.birthday ? ` ・ 誕生日: ${customer.birthday}` : ""}
          </p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            customer.line_user_id
              ? "bg-green-100 text-green-700"
              : "bg-neutral-100 text-neutral-500"
          }`}
        >
          {customer.line_user_id ? "LINE連携済み" : "LINE未連携"}
        </span>
      </div>

      {!customer.line_user_id && (
        <div className="rounded-xl border border-neutral-200 bg-white p-5 text-sm shadow-sm">
          <p className="font-medium text-neutral-900">LINE連携方法</p>
          <p className="mt-1 text-neutral-500">
            サロンのLINE公式アカウントを友だち追加後、トーク画面で以下の連携コードを送信するよう
            お客様にご案内してください。
          </p>
          <p className="mt-3 inline-block rounded-md bg-neutral-100 px-4 py-2 font-mono text-base tracking-wider text-neutral-900">
            {linkingCode}
          </p>
        </div>
      )}

      {customer.notes && (
        <div className="rounded-xl border border-neutral-200 bg-white p-5 text-sm shadow-sm">
          <p className="font-medium text-neutral-900">メモ</p>
          <p className="mt-1 whitespace-pre-wrap text-neutral-600">{customer.notes}</p>
        </div>
      )}

      <details className="rounded-xl border border-neutral-200 bg-white shadow-sm" open>
        <summary className="cursor-pointer select-none px-5 py-4 text-sm font-semibold text-neutral-900">
          + 来店記録を追加
        </summary>
        <form
          action={addVisitRecord}
          className="space-y-4 border-t border-neutral-100 px-5 py-4"
        >
          <input type="hidden" name="customerId" value={customer.id} />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-neutral-700">来店日</label>
              <input
                name="visitDate"
                type="date"
                defaultValue={new Date().toISOString().slice(0, 10)}
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700">メニュー</label>
              <input
                name="menu"
                placeholder="カット＋カラー"
                className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-neutral-700">
              施術メモ（薬剤・要望など）
            </label>
            <textarea
              name="memo"
              rows={3}
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800"
          >
            記録する
          </button>
        </form>
      </details>

      <div className="rounded-xl border border-neutral-200 bg-white shadow-sm">
        <div className="border-b border-neutral-200 px-5 py-4">
          <h2 className="text-sm font-semibold text-neutral-900">来店履歴（カルテ）</h2>
        </div>
        <ul className="divide-y divide-neutral-100">
          {(visits ?? []).length === 0 && (
            <li className="px-5 py-6 text-sm text-neutral-400">来店記録がありません</li>
          )}
          {(visits ?? []).map((visit) => (
            <li key={visit.id} className="px-5 py-4">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-neutral-900">{visit.visit_date}</p>
                <p className="text-xs text-neutral-500">
                  {(visit.staff as unknown as { name: string } | null)?.name}
                </p>
              </div>
              {visit.menu && <p className="mt-1 text-sm text-neutral-700">{visit.menu}</p>}
              {visit.memo && (
                <p className="mt-1 whitespace-pre-wrap text-sm text-neutral-500">{visit.memo}</p>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
