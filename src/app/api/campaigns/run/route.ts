import { NextResponse, type NextRequest } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { runCampaignsForSalon } from "@/lib/campaigns/run";

/**
 * Triggered once a day by an external scheduler (e.g. Vercel Cron or a
 * GitHub Actions cron workflow) hitting this URL with
 * `Authorization: Bearer $CRON_SECRET`. Runs every salon's active
 * campaigns and returns a per-salon summary.
 */
export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("authorization");
  const expected = `Bearer ${process.env.CRON_SECRET}`;

  if (!process.env.CRON_SECRET || authHeader !== expected) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const admin = createAdminClient();
  const { data: salons } = await admin.from("salons").select("id");

  const results = [];
  for (const salon of salons ?? []) {
    const result = await runCampaignsForSalon(salon.id);
    results.push({ salonId: salon.id, ...result });
  }

  return NextResponse.json({ results });
}
