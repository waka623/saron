import { requireCurrentSalon } from "@/lib/auth/current-salon";
import { logout } from "@/app/login/actions";
import { Sidebar } from "@/components/sidebar";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { salon } = await requireCurrentSalon();

  return (
    <div className="flex min-h-screen flex-col bg-stone-50 sm:flex-row">
      <Sidebar salonName={salon.name} logoutAction={logout} />
      <main className="flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto max-w-5xl">{children}</div>
      </main>
    </div>
  );
}
