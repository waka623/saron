export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {icon && <div className="text-stone-300">{icon}</div>}
      <div>
        <p className="text-sm font-medium text-stone-700">{title}</p>
        {description && <p className="mt-1 text-sm text-stone-400">{description}</p>}
      </div>
      {action}
    </div>
  );
}
