"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  IconDashboard,
  IconUsers,
  IconMegaphone,
  IconChat,
  IconMenu,
  IconX,
  IconLogOut,
} from "@/components/icons";

const NAV_ITEMS = [
  { href: "/dashboard", label: "ダッシュボード", icon: IconDashboard },
  { href: "/customers", label: "顧客・カルテ", icon: IconUsers },
  { href: "/campaigns", label: "リピート促進", icon: IconMegaphone },
  { href: "/line-settings", label: "LINE連携設定", icon: IconChat },
];

export function Sidebar({
  salonName,
  logoutAction,
}: {
  salonName: string;
  logoutAction: () => void;
}) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const nav = (
    <>
      <div className="border-b border-stone-200 px-5 py-4">
        <p className="text-xs font-medium text-stone-400">サロン</p>
        <p className="truncate text-sm font-semibold text-stone-900">{salonName}</p>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-rose-50 text-rose-700"
                  : "text-stone-600 hover:bg-stone-100 hover:text-stone-900"
              }`}
            >
              <Icon className={`h-4.5 w-4.5 shrink-0 ${active ? "text-rose-600" : "text-stone-400"}`} />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <form action={logoutAction} className="border-t border-stone-200 p-3">
        <button
          type="submit"
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-medium text-stone-500 hover:bg-stone-100"
        >
          <IconLogOut className="h-4.5 w-4.5" />
          ログアウト
        </button>
      </form>
    </>
  );

  return (
    <>
      {/* Mobile top bar */}
      <div className="flex items-center justify-between border-b border-stone-200 bg-white px-4 py-3 sm:hidden">
        <p className="text-sm font-semibold text-stone-900">{salonName}</p>
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          aria-label="メニューを開く"
          className="rounded-md p-1.5 text-stone-500 hover:bg-stone-100"
        >
          <IconMenu className="h-5 w-5" />
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 sm:hidden">
          <div
            className="absolute inset-0 bg-stone-900/40"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-white shadow-xl">
            <div className="flex items-center justify-end px-3 pt-3">
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                aria-label="メニューを閉じる"
                className="rounded-md p-1.5 text-stone-500 hover:bg-stone-100"
              >
                <IconX className="h-5 w-5" />
              </button>
            </div>
            {nav}
          </aside>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-stone-200 bg-white sm:flex">
        {nav}
      </aside>
    </>
  );
}
