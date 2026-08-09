export type ActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const idleState: ActionState = { status: "idle" };
