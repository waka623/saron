"use client";

import { SubmitButton } from "@/components/ui/button";
import { toggleCampaign } from "./actions";

export function CampaignToggleButton({
  campaignId,
  isActive,
}: {
  campaignId: string;
  isActive: boolean;
}) {
  return (
    <form action={toggleCampaign.bind(null, campaignId, !isActive)}>
      <SubmitButton variant="ghost" size="sm" pendingText="更新中...">
        {isActive ? "停止する" : "再開する"}
      </SubmitButton>
    </form>
  );
}
