import { createHmac, timingSafeEqual } from "node:crypto";

const LINE_API_BASE = "https://api.line.me/v2/bot";

export function verifyLineSignature(
  rawBody: string,
  signature: string | null,
  channelSecret: string
): boolean {
  if (!signature) return false;

  const expected = createHmac("sha256", channelSecret).update(rawBody).digest("base64");
  const expectedBuf = Buffer.from(expected);
  const actualBuf = Buffer.from(signature);

  if (expectedBuf.length !== actualBuf.length) return false;
  return timingSafeEqual(expectedBuf, actualBuf);
}

type LineTextMessage = { type: "text"; text: string };

async function callLineApi(path: string, accessToken: string, body: unknown) {
  const res = await fetch(`${LINE_API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`LINE API error (${res.status}): ${detail}`);
  }
}

export async function pushLineMessage(
  accessToken: string,
  to: string,
  text: string
) {
  const messages: LineTextMessage[] = [{ type: "text", text }];
  await callLineApi("/message/push", accessToken, { to, messages });
}

export async function replyLineMessage(
  accessToken: string,
  replyToken: string,
  text: string
) {
  const messages: LineTextMessage[] = [{ type: "text", text }];
  await callLineApi("/message/reply", accessToken, { replyToken, messages });
}
