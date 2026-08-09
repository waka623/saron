import Link from "next/link";
import { notFound } from "next/navigation";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { Card, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Disclosure } from "@/components/ui/disclosure";
import { EmptyState } from "@/components/ui/empty-state";
import { IconCalendarOff } from "@/components/icons";
import { VisitForm } from "./visit-form";

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
    <div className="space-y-6">
      <Link href="/customers" className="text-sm text-stone-500 hover:text-rose-700">
        ← 顧客一覧に戻る
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-stone-900">{customer.name}</h1>
          <p className="mt-1 text-sm text-stone-500">
            {customer.phone ?? "電話番号未登録"}
            {customer.birthday ? ` ・ 誕生日: ${customer.birthday}` : ""}
          </p>
        </div>
        <Badge tone={customer.line_user_id ? "success" : "neutral"}>
          {customer.line_user_id ? "LINE連携済み" : "LINE未連携"}
        </Badge>
      </div>

      {!customer.line_user_id && (
        <Card className="p-5 text-sm">
          <p className="font-medium text-stone-900">LINE連携方法</p>
          <p className="mt-1 text-stone-500">
            サロンのLINE公式アカウントを友だち追加後、トーク画面で以下の連携コードを送信するよう
            お客様にご案内してください。
          </p>
          <p className="mt-3 inline-block rounded-lg bg-rose-50 px-4 py-2 font-mono text-base tracking-wider text-rose-700">
            {linkingCode}
          </p>
        </Card>
      )}

      {customer.notes && (
        <Card className="p-5 text-sm">
          <p className="font-medium text-stone-900">メモ</p>
          <p className="mt-1 whitespace-pre-wrap text-stone-600">{customer.notes}</p>
        </Card>
      )}

      <Disclosure label="来店記録を追加" defaultOpen>
        <VisitForm customerId={customer.id} />
      </Disclosure>

      <Card>
        <CardHeader title="来店履歴（カルテ）" />
        {(visits ?? []).length === 0 ? (
          <EmptyState
            icon={<IconCalendarOff className="h-9 w-9" />}
            title="来店記録がありません"
            description="上の「来店記録を追加」から記録を始めましょう"
          />
        ) : (
          <ul className="divide-y divide-stone-100">
            {(visits ?? []).map((visit) => (
              <li key={visit.id} className="px-5 py-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-stone-900">{visit.visit_date}</p>
                  <p className="text-xs text-stone-500">
                    {(visit.staff as unknown as { name: string } | null)?.name}
                  </p>
                </div>
                {visit.menu && <p className="mt-1 text-sm text-stone-700">{visit.menu}</p>}
                {visit.memo && (
                  <p className="mt-1 whitespace-pre-wrap text-sm text-stone-500">{visit.memo}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
