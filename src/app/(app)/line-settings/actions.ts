"use server";

import { revalidatePath } from "next/cache";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { createClient } from "@/lib/supabase/server";
import type { ActionState } from "@/lib/action-state";

export async function saveLineSettings(
  _prevState: ActionState,
  formData: FormData
): Promise<ActionState> {
  const { salon } = await requireCurrentSalon();

  const channelId = String(formData.get("channelId") ?? "").trim() || null;
  const channelSecret = String(formData.get("channelSecret") ?? "").trim() || null;
  const channelAccessToken =
    String(formData.get("channelAccessToken") ?? "").trim() || null;

  const supabase = await createClient();
  const { error } = await supabase
    .from("salons")
    .update({
      line_channel_id: channelId,
      line_channel_secret: channelSecret,
      line_channel_access_token: channelAccessToken,
    })
    .eq("id", salon.id);

  if (error) {
    return { status: "error", message: error.message };
  }

  revalidatePath("/line-settings");
  return { status: "success", message: "LINE連携設定を保存しました" };
}
