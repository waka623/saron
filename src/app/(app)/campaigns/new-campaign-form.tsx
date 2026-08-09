"use client";

import { useActionState, useState } from "react";
import { Disclosure } from "@/components/ui/disclosure";
import { Field, inputClass } from "@/components/ui/field";
import { SubmitButton } from "@/components/ui/button";
import { FormMessage } from "@/components/ui/form-message";
import { idleState } from "@/lib/action-state";
import { createCampaign } from "./actions";
import type { CampaignType } from "@/types/database";

export function NewCampaignForm() {
  const [state, formAction] = useActionState(createCampaign, idleState);
  const [type, setType] = useState<CampaignType>("birthday");

  return (
    <Disclosure label="新しい配信ルールを作成">
      <form action={formAction} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="配信名" htmlFor="name">
            <input
              id="name"
              name="name"
              required
              placeholder="お誕生日クーポン"
              className={inputClass}
            />
          </Field>
          <Field label="種類" htmlFor="type">
            <select
              id="type"
              name="type"
              required
              value={type}
              onChange={(e) => setType(e.target.value as CampaignType)}
              className={inputClass}
            >
              <option value="birthday">誕生日クーポン</option>
              <option value="no_visit_reminder">休眠顧客リマインド</option>
              <option value="custom">カスタム（手動送信予定）</option>
            </select>
          </Field>
          {type === "no_visit_reminder" && (
            <Field label="未来店日数" htmlFor="daysSinceLastVisit">
              <input
                id="daysSinceLastVisit"
                name="daysSinceLastVisit"
                type="number"
                min={1}
                placeholder="60"
                className={inputClass}
              />
            </Field>
          )}
        </div>
        <Field
          label="メッセージ本文"
          htmlFor="messageTemplate"
          hint="{{name}} と書くとお客様名を挿入できます"
        >
          <textarea
            id="messageTemplate"
            name="messageTemplate"
            required
            rows={3}
            placeholder={
              "{{name}}様、お誕生日おめでとうございます！次回ご来店時に使える500円クーポンをプレゼント🎁"
            }
            className={inputClass}
          />
        </Field>
        <div className="flex items-center gap-3">
          <SubmitButton pendingText="作成中...">作成する</SubmitButton>
          <FormMessage state={state} />
        </div>
      </form>
    </Disclosure>
  );
}
