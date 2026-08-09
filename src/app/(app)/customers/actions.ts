"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { idleState, type ActionState } from "@/lib/action-state";

export async function createCustomer(
  _prevState: ActionState,
  formData: FormData
): Promise<ActionState> {
  const { salon } = await requireCurrentSalon();

  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { status: "error", message: "お名前を入力してください" };

  const phone = String(formData.get("phone") ?? "").trim() || null;
  const birthday = String(formData.get("birthday") ?? "").trim() || null;
  const notes = String(formData.get("notes") ?? "").trim() || null;

  const supabase = await createClient();
  const { data, error } = await supabase
    .from("customers")
    .insert({ salon_id: salon.id, name, phone, birthday, notes })
    .select("id")
    .single();

  if (error || !data) {
    return { status: "error", message: error?.message ?? "顧客の登録に失敗しました" };
  }

  revalidatePath("/customers");
  redirect(`/customers/${data.id}`);
}

export async function addVisitRecord(
  _prevState: ActionState,
  formData: FormData
): Promise<ActionState> {
  const { salon } = await requireCurrentSalon();

  const customerId = String(formData.get("customerId") ?? "");
  if (!customerId) return idleState;

  const visitDate = String(formData.get("visitDate") ?? "").trim();
  const menu = String(formData.get("menu") ?? "").trim() || null;
  const memo = String(formData.get("memo") ?? "").trim() || null;

  const supabase = await createClient();
  const { error } = await supabase.from("visit_records").insert({
    salon_id: salon.id,
    customer_id: customerId,
    visit_date: visitDate || new Date().toISOString().slice(0, 10),
    menu,
    memo,
  });

  if (error) {
    return { status: "error", message: error.message };
  }

  revalidatePath(`/customers/${customerId}`);
  revalidatePath("/dashboard");
  return { status: "success", message: "来店記録を追加しました" };
}
