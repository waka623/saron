"use client";

import Link from "next/link";
import { useActionState } from "react";
import { signup } from "./actions";
import type { AuthFormState } from "@/app/login/actions";

const initialState: AuthFormState = { error: null };

export default function SignupPage() {
  const [state, formAction, pending] = useActionState(signup, initialState);

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <div className="w-full max-w-sm rounded-xl border border-neutral-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-neutral-900">新規サロン登録</h1>
        <p className="mt-1 text-sm text-neutral-500">
          顧客カルテとLINEリピート促進を今すぐ始められます
        </p>

        <form action={formAction} className="mt-6 space-y-4">
          <div>
            <label htmlFor="salonName" className="block text-sm font-medium text-neutral-700">
              サロン名
            </label>
            <input
              id="salonName"
              name="salonName"
              type="text"
              required
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-neutral-700">
              メールアドレス
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              autoComplete="email"
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-neutral-700">
              パスワード（8文字以上）
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none"
            />
          </div>

          {state.error && (
            <p className="text-sm text-red-600" role="alert">
              {state.error}
            </p>
          )}

          <button
            type="submit"
            disabled={pending}
            className="w-full rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
          >
            {pending ? "登録中..." : "登録する"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-neutral-500">
          既にアカウントをお持ちの方は{" "}
          <Link href="/login" className="font-medium text-neutral-900 underline">
            ログイン
          </Link>
        </p>
      </div>
    </div>
  );
}
