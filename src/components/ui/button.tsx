"use client";

import { useFormStatus } from "react-dom";
import { IconSpinner } from "@/components/icons";

const VARIANTS = {
  primary:
    "bg-rose-600 text-white hover:bg-rose-700 focus-visible:outline-rose-600 disabled:bg-rose-300",
  secondary:
    "bg-white text-stone-700 border border-stone-300 hover:bg-stone-50 focus-visible:outline-stone-400 disabled:text-stone-400",
  ghost:
    "text-stone-500 hover:bg-stone-100 hover:text-stone-900 focus-visible:outline-stone-400 disabled:text-stone-300",
  danger:
    "bg-white text-red-600 border border-red-200 hover:bg-red-50 focus-visible:outline-red-500 disabled:text-red-300",
};

type Variant = keyof typeof VARIANTS;

type ButtonProps = {
  variant?: Variant;
  size?: "sm" | "md";
  children: React.ReactNode;
  pendingText?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

const SIZES = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2.5 text-sm",
};

/** Submit button that shows a spinner while its parent <form>'s action is pending. */
export function SubmitButton({
  variant = "primary",
  size = "md",
  children,
  pendingText,
  className = "",
  disabled,
  ...props
}: ButtonProps) {
  const { pending } = useFormStatus();

  return (
    <button
      type="submit"
      disabled={disabled || pending}
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...props}
    >
      {pending && <IconSpinner className="h-4 w-4 animate-spin" />}
      {pending && pendingText ? pendingText : children}
    </button>
  );
}

/** Plain button (no parent-form pending awareness) for non-submit actions like toggles. */
export function Button({
  variant = "secondary",
  size = "md",
  children,
  className = "",
  ...props
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
