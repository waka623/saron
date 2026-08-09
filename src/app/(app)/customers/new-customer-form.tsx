"use client";

import { useActionState } from "react";
import { Disclosure } from "@/components/ui/disclosure";
import { Field, inputClass } from "@/components/ui/field";
import { SubmitButton } from "@/components/ui/button";
import { FormMessage } from "@/components/ui/form-message";
import { idleState } from "@/lib/action-state";
import { createCustomer } from "./actions";

export function NewCustomerForm() {
  const [state, formAction] = useActionState(createCustomer, idleState);

  return (
    <Disclosure label="新しい顧客を登録">
      <form action={formAction} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="お名前" htmlFor="name">
            <input id="name" name="name" required className={inputClass} />
          </Field>
          <Field label="電話番号" htmlFor="phone">
            <input id="phone" name="phone" className={inputClass} />
          </Field>
          <Field label="誕生日" htmlFor="birthday">
            <input id="birthday" name="birthday" type="date" className={inputClass} />
          </Field>
        </div>
        <Field label="メモ（アレルギー、要望など）" htmlFor="notes">
          <textarea id="notes" name="notes" rows={2} className={inputClass} />
        </Field>
        <div className="flex items-center gap-3">
          <SubmitButton pendingText="登録中...">登録する</SubmitButton>
          <FormMessage state={state} />
        </div>
      </form>
    </Disclosure>
  );
}
