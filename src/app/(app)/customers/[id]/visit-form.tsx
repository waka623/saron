"use client";

import { useActionState, useRef, useEffect } from "react";
import { Field, inputClass } from "@/components/ui/field";
import { SubmitButton } from "@/components/ui/button";
import { FormMessage } from "@/components/ui/form-message";
import { idleState } from "@/lib/action-state";
import { addVisitRecord } from "../actions";

export function VisitForm({ customerId }: { customerId: string }) {
  const [state, formAction] = useActionState(addVisitRecord, idleState);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state.status === "success") formRef.current?.reset();
  }, [state]);

  return (
    <form ref={formRef} action={formAction} className="space-y-4">
      <input type="hidden" name="customerId" value={customerId} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="来店日" htmlFor="visitDate">
          <input
            id="visitDate"
            name="visitDate"
            type="date"
            defaultValue={new Date().toISOString().slice(0, 10)}
            className={inputClass}
          />
        </Field>
        <Field label="メニュー" htmlFor="menu">
          <input id="menu" name="menu" placeholder="カット＋カラー" className={inputClass} />
        </Field>
      </div>
      <Field label="施術メモ（薬剤・要望など）" htmlFor="memo">
        <textarea id="memo" name="memo" rows={3} className={inputClass} />
      </Field>
      <div className="flex items-center gap-3">
        <SubmitButton pendingText="記録中...">記録する</SubmitButton>
        <FormMessage state={state} />
      </div>
    </form>
  );
}
