"use client";

import Link from "next/link";
import { useActionState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { Field, inputClass } from "@/components/ui/field";
import { IconAlertTriangle, IconSpinner } from "@/components/icons";
import { signup } from "./actions";
import type { AuthFormState } from "@/app/login/actions";

const initialState: AuthFormState = { error: null };

export default function SignupPage() {
  const [state, formAction, pending] = useActionState(signup, initialState);

  return (
    <AuthShell
      title="新規サロン登録"
      subtitle="顧客カルテとLINEリピート促進を今すぐ始められます"
      footer={
        <>
          既にアカウントをお持ちの方は{" "}
          <Link href="/login" className="font-medium text-rose-700 hover:underline">
            ログイン
          </Link>
        </>
      }
    >
      <form action={formAction} className="mt-6 space-y-4">
        <Field label="サロン名" htmlFor="salonName">
          <input id="salonName" name="salonName" type="text" required className={inputClass} />
        </Field>
        <Field label="メールアドレス" htmlFor="email">
          <input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            className={inputClass}
          />
        </Field>
        <Field label="パスワード（8文字以上）" htmlFor="password">
          <input
            id="password"
            name="password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            className={inputClass}
          />
        </Field>

        {state.error && (
          <p role="alert" className="flex items-center gap-1.5 text-sm text-red-600">
            <IconAlertTriangle className="h-4 w-4 shrink-0" />
            {state.error}
          </p>
        )}

        <button
          type="submit"
          disabled={pending}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-rose-700 disabled:bg-rose-300"
        >
          {pending && <IconSpinner className="h-4 w-4 animate-spin" />}
          {pending ? "登録中..." : "登録する"}
        </button>
      </form>
    </AuthShell>
  );
}
