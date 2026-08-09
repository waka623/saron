import Link from "next/link";
import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { logout } from "@/app/login/actions";

const NAV_ITEMS = [
  { href: "/dashboard", label: "ダッシュボード" },
  { href: "/customers", label: "顧客・カルテ" },
  { href: "/campaigns", label: "リピート促進" },
  { href: "/line-settings", label: "LINE連携設定" },
];

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { salon } = await requireCurrentSalon();

  return (
    <div className="flex min-h-screen bg-neutral-50">
      <aside className="flex w-60 flex-col border-r border-neutral-200 bg-white">
        <div className="border-b border-neutral-200 px-5 py-4">
          <p className="text-xs font-medium text-neutral-400">サロン</p>
          <p className="truncate text-sm font-semibold text-neutral-900">{salon.name}</p>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-4">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="block rounded-md px-3 py-2 text-sm font-medium text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <form action={logout} className="border-t border-neutral-200 p-3">
          <button
            type="submit"
            className="w-full rounded-md px-3 py-2 text-left text-sm font-medium text-neutral-500 hover:bg-neutral-100"
          >
            ログアウト
          </button>
        </form>
      </aside>
      <main className="flex-1 px-8 py-8">{children}</main>
    </div>
  );
}
