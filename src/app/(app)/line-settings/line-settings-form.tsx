"use client";

import { useActionState } from "react";
import { Field, inputClass } from "@/components/ui/field";
import { SubmitButton } from "@/components/ui/button";
import { FormMessage } from "@/components/ui/form-message";
import { idleState } from "@/lib/action-state";
import { saveLineSettings } from "./actions";

export function LineSettingsForm({
  channelId,
  channelSecret,
  channelAccessToken,
}: {
  channelId: string | null;
  channelSecret: string | null;
  channelAccessToken: string | null;
}) {
  const [state, formAction] = useActionState(saveLineSettings, idleState);

  return (
    <form action={formAction} className="space-y-4">
      <Field label="チャネルID" htmlFor="channelId">
        <input
          id="channelId"
          name="channelId"
          defaultValue={channelId ?? ""}
          className={inputClass}
        />
      </Field>
      <Field label="チャネルシークレット" htmlFor="channelSecret">
        <input
          id="channelSecret"
          name="channelSecret"
          type="password"
          defaultValue={channelSecret ?? ""}
          className={inputClass}
        />
      </Field>
      <Field label="チャネルアクセストークン（長期）" htmlFor="channelAccessToken">
        <input
          id="channelAccessToken"
          name="channelAccessToken"
          type="password"
          defaultValue={channelAccessToken ?? ""}
          className={inputClass}
        />
      </Field>
      <div className="flex items-center gap-3">
        <SubmitButton pendingText="保存中...">保存する</SubmitButton>
        <FormMessage state={state} />
      </div>
    </form>
  );
}
