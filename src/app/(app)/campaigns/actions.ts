"use server";

import { revalidatePath } from "next/cache";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import { runCampaignsForSalon } from "@/lib/campaigns/run";
import type { CampaignType } from "@/types/database";

export async function createCampaign(formData: FormData) {
  const { salon } = await requireCurrentSalon();

  const name = String(formData.get("name") ?? "").trim();
  const type = String(formData.get("type") ?? "") as CampaignType;
  const messageTemplate = String(formData.get("messageTemplate") ?? "").trim();
  const daysRaw = String(formData.get("daysSinceLastVisit") ?? "").trim();

  if (!name || !messageTemplate) return;
  if (!["birthday", "no_visit_reminder", "custom"].includes(type)) return;

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

  if (error) throw new Error(error.message);

  revalidatePath("/campaigns");
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

export async function runCampaignsNow() {
  const { salon } = await requireCurrentSalon();
  await runCampaignsForSalon(salon.id);
  revalidatePath("/campaigns");
}
