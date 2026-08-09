"use client";

import { useActionState } from "react";
import { SubmitButton } from "@/components/ui/button";
import { FormMessage } from "@/components/ui/form-message";
import { idleState } from "@/lib/action-state";
import { runCampaignsNow } from "./actions";

export function RunNowButton({ disabled }: { disabled: boolean }) {
  const [state, formAction] = useActionState(runCampaignsNow, idleState);

  return (
    <div className="flex flex-col items-end gap-2">
      <form action={formAction}>
        <SubmitButton variant="secondary" disabled={disabled} pendingText="実行中...">
          今すぐ配信を実行
        </SubmitButton>
      </form>
      <FormMessage state={state} />
    </div>
  );
}
