"use server";

import { revalidatePath } from "next/cache";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { runCampaignsForSalon } from "@/lib/campaigns/run";
import type { CampaignType } from "@/types/database";
import type { ActionState } from "@/lib/action-state";

export async function createCampaign(
  _prevState: ActionState,
  formData: FormData
): Promise<ActionState> {
  const { salon } = await requireCurrentSalon();

  const name = String(formData.get("name") ?? "").trim();
  const type = String(formData.get("type") ?? "") as CampaignType;
  const messageTemplate = String(formData.get("messageTemplate") ?? "").trim();
  const daysRaw = String(formData.get("daysSinceLastVisit") ?? "").trim();

  if (!name || !messageTemplate) {
    return { status: "error", message: "配信名とメッセージ本文を入力してください" };
  }
  if (!["birthday", "no_visit_reminder", "custom"].includes(type)) {
    return { status: "error", message: "配信の種類を選択してください" };
  }

  const daysSinceLastVisit =
    type === "no_visit_reminder" && daysRaw ? Number.parseInt(daysRaw, 10) : null;

  const supabase = await createClient();
  const { error } = await supabase.from("campaigns").insert({
    salon_id: salon.id,
    name,
    type,
    days_since_last_visit: daysSinceLastVisit,
    message_template: messageTemplate,
    is_active: true,
  });

  if (error) return { status: "error", message: error.message };

  revalidatePath("/campaigns");
  return { status: "success", message: "配信ルールを作成しました" };
}

export async function toggleCampaign(campaignId: string, isActive: boolean) {
  const { salon } = await requireCurrentSalon();
  const supabase = await createClient();

  const { error } = await supabase
    .from("campaigns")
    .update({ is_active: isActive })
    .eq("id", campaignId)
    .eq("salon_id", salon.id);

  if (error) throw new Error(error.message);

  revalidatePath("/campaigns");
}

export async function runCampaignsNow(): Promise<ActionState> {
  const { salon } = await requireCurrentSalon();
  const result = await runCampaignsForSalon(salon.id);
  revalidatePath("/campaigns");

  if (result.sent + result.skipped + result.failed === 0) {
    return { status: "success", message: "本日配信対象のお客様はいませんでした" };
  }
  return {
    status: result.failed > 0 ? "error" : "success",
    message: `送信 ${result.sent}件 / スキップ ${result.skipped}件 / 失敗 ${result.failed}件`,
  };
}
