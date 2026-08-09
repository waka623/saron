"use client";

import { useEffect, useState } from "react";
import { IconCheckCircle, IconAlertTriangle } from "@/components/icons";
import type { ActionState } from "@/lib/action-state";

export function FormMessage({ state }: { state: ActionState }) {
  const [lastState, setLastState] = useState(state);
  const [dismissed, setDismissed] = useState(false);

  // React-recommended "adjust state during render" pattern instead of an
  // effect: reset the dismissed flag the moment a new state object arrives.
  if (state !== lastState) {
    setLastState(state);
    setDismissed(false);
  }

  useEffect(() => {
    if (state.status !== "success") return;
    const timer = setTimeout(() => setDismissed(true), 4000);
    return () => clearTimeout(timer);
  }, [state]);

  if (dismissed || state.status === "idle" || !state.message) return null;

  const isError = state.status === "error";

  return (
    <p
      role={isError ? "alert" : "status"}
      className={`animate-fade-in flex items-center gap-1.5 text-sm ${
        isError ? "text-red-600" : "text-emerald-600"
      }`}
    >
      {isError ? (
        <IconAlertTriangle className="h-4 w-4 shrink-0" />
      ) : (
        <IconCheckCircle className="h-4 w-4 shrink-0" />
      )}
      {state.message}
    </p>
  );
}
