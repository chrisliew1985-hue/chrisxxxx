import crypto from "node:crypto";

/**
 * Verifies Meta's `X-Hub-Signature-256` header against the raw request body.
 * Without this check anyone who learns the webhook URL can make the bot reply
 * to arbitrary numbers on your account.
 */
export function verifySignature(
  rawBody: Buffer | string,
  header: string | undefined,
  appSecret: string,
): boolean {
  if (!header?.startsWith("sha256=")) return false;

  const expected = crypto
    .createHmac("sha256", appSecret)
    .update(rawBody)
    .digest("hex");
  const received = header.slice("sha256=".length);

  // Both buffers must be the same length before timingSafeEqual will run.
  if (received.length !== expected.length) return false;
  return crypto.timingSafeEqual(Buffer.from(received, "utf8"), Buffer.from(expected, "utf8"));
}
