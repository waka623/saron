export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-stone-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-rose-600 text-lg font-semibold text-white">
            サ
          </div>
          <p className="text-sm font-medium text-stone-400">サロンリピート</p>
        </div>
        <div className="rounded-xl border border-stone-200 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold text-stone-900">{title}</h1>
          <p className="mt-1 text-sm text-stone-500">{subtitle}</p>
          {children}
        </div>
        <p className="mt-6 text-center text-sm text-stone-500">{footer}</p>
      </div>
    </div>
  );
}
