"use client";

import { useState } from "react";
import { IconPlus, IconChevronDown } from "@/components/icons";

export function Disclosure({
  label,
  defaultOpen = false,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-stone-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-5 py-4 text-left text-sm font-semibold text-stone-900"
      >
        <span className="flex items-center gap-2">
          <IconPlus className="h-4 w-4 text-rose-600" />
          {label}
        </span>
        <IconChevronDown
          className={`h-4 w-4 text-stone-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="animate-fade-in space-y-4 border-t border-stone-100 px-5 py-4">
          {children}
        </div>
      )}
    </div>
  );
}
