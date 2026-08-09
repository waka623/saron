import { createAdminClient } from "@/lib/supabase/admin";
import { pushLineMessage } from "@/lib/line/messaging";
import type { Campaign, Customer } from "@/types/database";

const BIRTHDAY_RESEND_COOLDOWN_DAYS = 300;

export type CampaignRunResult = { sent: number; skipped: number; failed: number };

function renderMessage(template: string, customer: Customer): string {
  return template.replaceAll("{{name}}", customer.name);
}

function daysAgo(days: number): Date {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d;
}

function isSameMonthDay(dateStr: string, reference: Date): boolean {
  const d = new Date(dateStr);
  return d.getMonth() === reference.getMonth() && d.getDate() === reference.getDate();
}

async function wasRecentlySent(
  admin: ReturnType<typeof createAdminClient>,
  campaignId: string,
  customerId: string,
  cooldownDays: number
): Promise<boolean> {
  const { data } = await admin
    .from("campaign_logs")
    .select("sent_at")
    .eq("campaign_id", campaignId)
    .eq("customer_id", customerId)
    .eq("status", "sent")
    .gte("sent_at", daysAgo(cooldownDays).toISOString())
    .limit(1);

  return (data ?? []).length > 0;
}

async function sendToCustomer(
  admin: ReturnType<typeof createAdminClient>,
  accessToken: string,
  campaign: Campaign,
  customer: Customer
): Promise<"sent" | "failed"> {
  const text = renderMessage(campaign.message_template, customer);
  try {
    await pushLineMessage(accessToken, customer.line_user_id!, text);
    await admin.from("campaign_logs").insert({
      campaign_id: campaign.id,
      customer_id: customer.id,
      status: "sent",
    });
    return "sent";
  } catch (err) {
    await admin.from("campaign_logs").insert({
      campaign_id: campaign.id,
      customer_id: customer.id,
      status: "failed",
      error_message: err instanceof Error ? err.message : "unknown error",
    });
    return "failed";
  }
}

/**
 * Matches active campaigns against the salon's customers and sends LINE
 * push messages for the ones due today. Intended to run once per day
 * (see /api/campaigns/run), and safe to re-run: each send is deduplicated
 * against campaign_logs so re-running the same day won't double-send.
 */
export async function runCampaignsForSalon(salonId: string): Promise<CampaignRunResult> {
  const admin = createAdminClient();
  const result: CampaignRunResult = { sent: 0, skipped: 0, failed: 0 };

  const { data: salon } = await admin
    .from("salons")
    .select("id, line_channel_access_token")
    .eq("id", salonId)
    .single();

  if (!salon?.line_channel_access_token) {
    return result;
  }
  const accessToken = salon.line_channel_access_token;

  const { data: campaigns } = await admin
    .from("campaigns")
    .select("*")
    .eq("salon_id", salonId)
    .eq("is_active", true);

  if (!campaigns?.length) return result;

  const { data: linkedCustomers } = await admin
    .from("customers")
    .select("*")
    .eq("salon_id", salonId)
    .not("line_user_id", "is", null);

  const customers = linkedCustomers ?? [];
  const today = new Date();

  for (const campaign of campaigns) {
    if (campaign.type === "birthday") {
      const candidates = customers.filter(
        (c) => c.birthday && isSameMonthDay(c.birthday, today)
      );
      for (const customer of candidates) {
        if (
          await wasRecentlySent(
            admin,
            campaign.id,
            customer.id,
            BIRTHDAY_RESEND_COOLDOWN_DAYS
          )
        ) {
          result.skipped++;
          continue;
        }
        const outcome = await sendToCustomer(admin, accessToken, campaign, customer);
        result[outcome]++;
      }
      continue;
    }

    if (campaign.type === "no_visit_reminder" && campaign.days_since_last_visit) {
      const { data: visits } = await admin
        .from("visit_records")
        .select("customer_id, visit_date")
        .eq("salon_id", salonId)
        .order("visit_date", { ascending: false });

      const lastVisitByCustomer = new Map<string, string>();
      for (const v of visits ?? []) {
        if (!lastVisitByCustomer.has(v.customer_id)) {
          lastVisitByCustomer.set(v.customer_id, v.visit_date);
        }
      }

      const cutoff = daysAgo(campaign.days_since_last_visit);
      const candidates = customers.filter((c) => {
        const lastVisit = lastVisitByCustomer.get(c.id);
        return lastVisit && new Date(lastVisit) <= cutoff;
      });

      for (const customer of candidates) {
        if (
          await wasRecentlySent(
            admin,
            campaign.id,
            customer.id,
            campaign.days_since_last_visit
          )
        ) {
          result.skipped++;
          continue;
        }
        const outcome = await sendToCustomer(admin, accessToken, campaign, customer);
        result[outcome]++;
      }
    }

    // "custom" campaigns are not auto-triggered in the MVP — reserved for
    // future one-off/manual broadcasts.
  }

  return result;
}
