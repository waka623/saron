import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import type { Salon } from "@/types/database";

/**
 * Resolves the salon owned by the signed-in user. Every dashboard page is
 * scoped to exactly one salon per owner for the MVP, so this is the single
 * entry point pages use to get both the authenticated user and their salon.
 */
export async function requireCurrentSalon(): Promise<{
  userId: string;
  salon: Salon;
}> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const { data: salon, error } = await supabase
    .from("salons")
    .select("*")
    .eq("owner_id", user.id)
    .single();

  if (error || !salon) {
    redirect("/login");
  }

  return { userId: user.id, salon };
}
