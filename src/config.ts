import fs from "node:fs";
import path from "node:path";
import "dotenv/config";
import type { BusinessConfig } from "./types.js";

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `Missing required environment variable ${name}. Copy .env.example to .env and fill it in.`,
    );
  }
  return value;
}

function optionalNumber(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new Error(`Environment variable ${name} must be a number, got "${raw}".`);
  }
  return parsed;
}

/**
 * Credentials are exposed as getters so that importing any module — in a test,
 * or in the dry-run CLI — does not demand a full production environment.
 * `validateEnv()` forces the check once, at server startup.
 */
export const env = {
  port: optionalNumber("PORT", 3000),
  /** Token you invent, echoed back to Meta during webhook verification. */
  get verifyToken(): string {
    return required("WHATSAPP_VERIFY_TOKEN");
  },
  /** Permanent access token from your Meta system user. */
  get accessToken(): string {
    return required("WHATSAPP_ACCESS_TOKEN");
  },
  /** Phone Number ID from the WhatsApp > API Setup screen (not the phone number). */
  get phoneNumberId(): string {
    return required("WHATSAPP_PHONE_NUMBER_ID");
  },
  /** App Secret — used to verify that webhook calls really came from Meta. */
  get appSecret(): string {
    return required("WHATSAPP_APP_SECRET");
  },
  graphVersion: process.env.GRAPH_API_VERSION ?? "v21.0",
  /** Unset disables the Claude fallback; rules still work. */
  anthropicApiKey: process.env.ANTHROPIC_API_KEY,
  model: process.env.CLAUDE_MODEL ?? "claude-opus-5",
  /** Max auto-replies to one contact per hour before the bot goes quiet. */
  maxRepliesPerHour: optionalNumber("MAX_REPLIES_PER_HOUR", 12),
  /** How long a chat stays paused after a handoff. */
  handoffHours: optionalNumber("HANDOFF_PAUSE_HOURS", 12),
  /** Conversation turns kept as context for Claude. */
  historyTurns: optionalNumber("HISTORY_TURNS", 12),
  dataDir: process.env.DATA_DIR ?? "data",
  configPath: process.env.BUSINESS_CONFIG ?? "config/business.json",
  /** Log inbound/outbound message bodies. Off by default — these are private. */
  logMessageBodies: process.env.LOG_MESSAGE_BODIES === "true",
};

/** Fails fast at startup if any WhatsApp credential is missing. */
export function validateEnv(): void {
  void env.verifyToken;
  void env.accessToken;
  void env.phoneNumberId;
  void env.appSecret;
}

/** Reads and lightly validates the editable business profile. */
export function loadBusinessConfig(configPath = env.configPath): BusinessConfig {
  const resolved = path.resolve(configPath);
  const raw = fs.readFileSync(resolved, "utf8");
  const parsed = JSON.parse(raw) as BusinessConfig;

  const missing = (["agentName", "agency", "timezone", "businessHours"] as const).filter(
    (key) => !parsed[key],
  );
  if (missing.length > 0) {
    throw new Error(`${resolved} is missing required field(s): ${missing.join(", ")}`);
  }
  if (!Array.isArray(parsed.rules)) {
    throw new Error(`${resolved} must contain a "rules" array (it may be empty).`);
  }

  const seen = new Set<string>();
  for (const rule of parsed.rules) {
    if (seen.has(rule.id)) {
      throw new Error(`${resolved} has two rules with id "${rule.id}".`);
    }
    seen.add(rule.id);
    if (rule.regex) {
      try {
        new RegExp(rule.regex, "i");
      } catch (error) {
        throw new Error(
          `Rule "${rule.id}" has an invalid regex: ${(error as Error).message}`,
        );
      }
    }
  }
  return parsed;
}
