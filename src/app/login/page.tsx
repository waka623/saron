"use client";

import Link from "next/link";
import { useActionState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { Field, inputClass } from "@/components/ui/field";
import { IconAlertTriangle, IconSpinner } from "@/components/icons";
import { login, type AuthFormState } from "./actions";

const initialState: AuthFormState = { error: null };

export default function LoginPage() {
  const [state, formAction, pending] = useActionState(login, initialState);

  return (
    <AuthShell
      title="サロン管理画面ログイン"
      subtitle="顧客カルテ・LINE配信の管理はこちらから"
      footer={
        <>
          アカウントをお持ちでない方は{" "}
          <Link href="/signup" className="font-medium text-rose-700 hover:underline">
            新規登録
          </Link>
        </>
      }
    >
      <form action={formAction} className="mt-6 space-y-4">
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
        <Field label="パスワード" htmlFor="password">
          <input
            id="password"
            name="password"
            type="password"
            required
            autoComplete="current-password"
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
          {pending ? "ログイン中..." : "ログイン"}
        </button>
      </form>
    </AuthShell>
  );
}
