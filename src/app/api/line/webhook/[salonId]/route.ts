import { NextResponse, type NextRequest } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { verifyLineSignature, replyLineMessage } from "@/lib/line/messaging";

type LineWebhookEvent = {
  type: string;
  replyToken?: string;
  source?: { userId?: string };
  message?: { type: string; text?: string };
};

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ salonId: string }> }
) {
  const { salonId } = await params;
  const rawBody = await request.text();
  const signature = request.headers.get("x-line-signature");

  const admin = createAdminClient();
  const { data: salon } = await admin
    .from("salons")
    .select("id, line_channel_secret, line_channel_access_token")
    .eq("id", salonId)
    .single();

  if (!salon?.line_channel_secret || !salon.line_channel_access_token) {
    // Unknown salon or LINE not configured yet — don't leak which case it is.
    return NextResponse.json({ ok: true });
  }

  if (!verifyLineSignature(rawBody, signature, salon.line_channel_secret)) {
    return NextResponse.json({ error: "invalid signature" }, { status: 401 });
  }

  const body = JSON.parse(rawBody) as { events?: LineWebhookEvent[] };
  const accessToken = salon.line_channel_access_token;

  for (const event of body.events ?? []) {
    if (event.type !== "message" || event.message?.type !== "text") continue;

    const userId = event.source?.userId;
    const text = event.message?.text?.trim().toUpperCase();
    if (!userId || !text) continue;

    const { data: unlinkedCustomers } = await admin
      .from("customers")
      .select("id, name, line_link_token")
      .eq("salon_id", salonId)
      .is("line_user_id", null);

    const match = (unlinkedCustomers ?? []).find(
      (customer) => customer.line_link_token.slice(0, 8).toUpperCase() === text
    );

    if (!match) continue;

    await admin.from("customers").update({ line_user_id: userId }).eq("id", match.id);

    if (event.replyToken) {
      await replyLineMessage(
        accessToken,
        event.replyToken,
        `${match.name}様、LINE連携が完了しました。今後のお知らせをこちらにお送りします。`
      );
    }
  }

  return NextResponse.json({ ok: true });
}
