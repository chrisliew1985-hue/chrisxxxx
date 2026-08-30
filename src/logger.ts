import { env } from "./config.js";

type Level = "info" | "warn" | "error";

function emit(level: Level, message: string, fields: Record<string, unknown> = {}): void {
  const line = JSON.stringify({
    ts: new Date().toISOString(),
    level,
    message,
    ...fields,
  });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

export const log = {
  info: (message: string, fields?: Record<string, unknown>) => emit("info", message, fields),
  warn: (message: string, fields?: Record<string, unknown>) => emit("warn", message, fields),
  error: (message: string, fields?: Record<string, unknown>) => emit("error", message, fields),
};

/**
 * Message bodies are private, so they are only logged when LOG_MESSAGE_BODIES=true.
 * Otherwise just the length is recorded, which is enough to debug delivery.
 */
export function redactBody(text: string): string {
  return env.logMessageBodies ? text : `<${text.length} chars>`;
}

/** Keeps the last 4 digits only — enough to correlate, not enough to dox. */
export function maskNumber(number: string): string {
  return number.length <= 4 ? "****" : `****${number.slice(-4)}`;
}
