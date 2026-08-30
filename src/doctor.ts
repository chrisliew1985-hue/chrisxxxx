/**
 * Setup checker. Tells you what is configured, what is missing, and what to do
 * about it — before you find out from a customer.
 *
 *   npm run doctor                     config and .env only, no network
 *   npm run doctor -- --live           also check the number with Meta
 *   npm run doctor -- --url https://…  also test your deployed webhook
 */
import crypto from "node:crypto";
import fs from "node:fs";
import { parseArgs } from "node:util";
import "dotenv/config";
import { loadBusinessConfig } from "./config.js";
import { matchRule, normalise, render, templateValues } from "./rules.js";
import type { BusinessConfig } from "./types.js";

const tick = "\u001b[32m✓\u001b[0m";
const cross = "\u001b[31m✗\u001b[0m";
const warn = "\u001b[33m!\u001b[0m";
const dim = (text: string) => `\u001b[2m${text}\u001b[0m`;
const bold = (text: string) => `\u001b[1m${text}\u001b[0m`;

let failures = 0;
let warnings = 0;

function pass(message: string): void {
  console.log(`  ${tick} ${message}`);
}

function fail(message: string, fix?: string): void {
  failures += 1;
  console.log(`  ${cross} ${message}`);
  if (fix) console.log(`    ${dim(`→ ${fix}`)}`);
}

function caution(message: string, fix?: string): void {
  warnings += 1;
  console.log(`  ${warn} ${message}`);
  if (fix) console.log(`    ${dim(`→ ${fix}`)}`);
}

function section(title: string): void {
  console.log(`\n${bold(title)}`);
}

/** Placeholders `render()` knows how to substitute. */
const KNOWN_PLACEHOLDERS = new Set([
  "agentName",
  "agency",
  "hours",
  "areas",
  "languages",
  "signOff",
  "name",
]);

const HOURS_PATTERN = /^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$/;

function checkBusinessConfig(config: BusinessConfig): void {
  section("config/business.json");

  if (config.agency === "Your Agency Name") {
    caution("agency is still the sample value", "Set your real agency name.");
  } else {
    pass(`Agency: ${config.agency}, agent: ${config.agentName}`);
  }

  // Timezone — an invalid IANA name makes every business-hours check wrong.
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: config.timezone });
    pass(`Timezone: ${config.timezone}`);
  } catch {
    fail(
      `Timezone "${config.timezone}" is not a valid IANA name`,
      'Use a name like "Asia/Kuala_Lumpur", not "GMT+8".',
    );
  }

  for (const [day, hours] of Object.entries(config.businessHours)) {
    if (hours !== null && !HOURS_PATTERN.test(hours)) {
      fail(
        `businessHours.${day} is "${hours}", which will not parse`,
        'Use "09:00-19:00", or null for a closed day.',
      );
    }
  }

  const available = config.listings.filter((listing) => listing.status === "available");
  if (config.listings.length === 0) {
    caution("No listings configured", "Claude will have nothing concrete to answer with.");
  } else if (available.length === 0) {
    caution(
      `${config.listings.length} listing(s), none marked "available"`,
      'Only status "available" listings are offered to customers.',
    );
  } else {
    pass(`${available.length} available listing(s) of ${config.listings.length}`);
  }

  const refs = new Set<string>();
  for (const listing of config.listings) {
    if (refs.has(listing.ref)) {
      fail(`Two listings share the ref "${listing.ref}"`, "Refs must be unique.");
    }
    refs.add(listing.ref);
  }

  pass(`${config.faq.length} FAQ entrie(s)`);
}

function checkRules(config: BusinessConfig): void {
  section("Reply rules");

  if (config.rules.length === 0) {
    caution("No rules configured", "Every message will go to Claude, which costs more.");
    return;
  }
  pass(`${config.rules.length} rules`);

  // Every reply that will ever be sent, checked for broken placeholders.
  const templates: { where: string; text: string }[] = [
    { where: "unsupportedMediaReply", text: config.unsupportedMediaReply },
    { where: "handoffReply", text: config.handoffReply },
    { where: "fallbackReply", text: config.fallbackReply },
  ];
  for (const rule of config.rules) {
    templates.push({ where: `rule "${rule.id}" reply`, text: rule.reply });
    if (rule.afterHoursReply) {
      templates.push({ where: `rule "${rule.id}" afterHoursReply`, text: rule.afterHoursReply });
    }
  }

  let badPlaceholders = 0;
  for (const { where, text } of templates) {
    for (const match of text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)) {
      const key = match[1] as string;
      if (!KNOWN_PLACEHOLDERS.has(key)) {
        badPlaceholders += 1;
        fail(
          `${where} uses {{${key}}}, which is not a real placeholder`,
          `Known: ${[...KNOWN_PLACEHOLDERS].map((name) => `{{${name}}}`).join(", ")}`,
        );
      }
    }
    if (!text.trim()) fail(`${where} is empty`, "A customer would get a blank message.");
  }
  if (badPlaceholders === 0) pass("All {{placeholders}} resolve");

  for (const rule of config.rules) {
    if (rule.keywords.length === 0 && !rule.regex) {
      fail(`Rule "${rule.id}" has no keywords and no regex`, "It can never match.");
    }
    for (const keyword of rule.keywords) {
      if (!normalise(keyword)) {
        fail(
          `Rule "${rule.id}" has keyword ${JSON.stringify(keyword)} with no letters or digits`,
          "Punctuation is stripped before matching, so this can never match.",
        );
      }
    }
  }

  // A keyword that another rule outscores is dead weight — tell them which.
  for (const rule of config.rules) {
    for (const keyword of rule.keywords) {
      const winner = matchRule(keyword, config.rules);
      if (winner && winner.rule.id !== rule.id) {
        caution(
          `Rule "${rule.id}" keyword "${keyword}" is taken by rule "${winner.rule.id}"`,
          `Raise "priority" on "${rule.id}" if it should win.`,
        );
      }
    }
  }

  const handoffRules = config.rules.filter((rule) => rule.handoff);
  if (handoffRules.length === 0) {
    caution(
      "No rule hands over to a human",
      'Add one matching "talk to a real person" so customers can always reach you.',
    );
  } else {
    pass(`${handoffRules.length} rule(s) hand over to you`);
  }

  // Show what a greeting actually renders as — typos are obvious here.
  const sample = matchRule("hi", config.rules);
  if (sample) {
    console.log(dim(`    sample reply: ${render(sample.rule.reply, templateValues(config))}`));
  }
}

function checkEnv(config: BusinessConfig): void {
  section("Environment (.env)");

  if (!fs.existsSync(".env")) {
    fail("No .env file", "cp .env.example .env, then fill it in.");
  }

  const required = [
    ["WHATSAPP_VERIFY_TOKEN", "A random string you also type into Meta's webhook form."],
    ["WHATSAPP_ACCESS_TOKEN", "Meta app > WhatsApp > API Setup, or a System User token."],
    ["WHATSAPP_PHONE_NUMBER_ID", "Meta app > WhatsApp > API Setup. A long number."],
    ["WHATSAPP_APP_SECRET", "Meta app > App settings > Basic > App Secret."],
  ] as const;

  for (const [name, hint] of required) {
    const value = process.env[name];
    if (!value) fail(`${name} is not set`, hint);
    else pass(`${name} is set`);
  }

  const phoneNumberId = process.env.WHATSAPP_PHONE_NUMBER_ID;
  if (phoneNumberId && !/^\d+$/.test(phoneNumberId)) {
    fail(
      `WHATSAPP_PHONE_NUMBER_ID is "${phoneNumberId}", which is not all digits`,
      "This is the Phone number ID, not the phone number itself.",
    );
  }

  const verifyToken = process.env.WHATSAPP_VERIFY_TOKEN;
  if (verifyToken === "pick-any-long-random-string") {
    fail("WHATSAPP_VERIFY_TOKEN is still the example value", "Invent your own random string.");
  } else if (verifyToken && verifyToken.length < 16) {
    caution("WHATSAPP_VERIFY_TOKEN is short", "Use something long and random.");
  }

  if (process.env.ANTHROPIC_API_KEY) {
    pass(`Claude enabled (${process.env.CLAUDE_MODEL ?? "claude-opus-5"})`);
  } else {
    caution(
      "ANTHROPIC_API_KEY not set — keyword rules only",
      "Fine for testing. Set it so unmatched questions get a real answer.",
    );
  }

  if (process.env.LOG_MESSAGE_BODIES === "true") {
    caution(
      "LOG_MESSAGE_BODIES=true writes customer messages to your logs",
      "Turn this off outside debugging.",
    );
  }

  if (!config.alertNumber) {
    caution(
      "alertNumber is empty — no handoff alerts",
      "Add your own number to config/business.json to get alerted.",
    );
  } else if (!/^\d{6,15}$/.test(config.alertNumber)) {
    fail(
      `alertNumber "${config.alertNumber}" is not E.164 digits`,
      'Digits only, country code first, no "+" and no spaces. e.g. 60123456789',
    );
  } else {
    pass(`Handoff alerts go to ${config.alertNumber}`);
  }
}

/** Confirms the token and phone number ID actually work against Meta. */
async function checkLive(): Promise<void> {
  section("Meta connection");

  const token = process.env.WHATSAPP_ACCESS_TOKEN;
  const phoneNumberId = process.env.WHATSAPP_PHONE_NUMBER_ID;
  const version = process.env.GRAPH_API_VERSION ?? "v21.0";
  if (!token || !phoneNumberId) {
    fail("Cannot check — access token or phone number ID missing");
    return;
  }

  const fields = "display_phone_number,verified_name,platform_type,quality_rating";
  const url = `https://graph.facebook.com/${version}/${phoneNumberId}?fields=${fields}`;

  try {
    const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    const payload = (await response.json()) as Record<string, unknown> & {
      error?: { message?: string; code?: number };
    };

    if (!response.ok) {
      const message = payload.error?.message ?? `HTTP ${response.status}`;
      fail(`Meta rejected the request: ${message}`, hintForGraphError(payload.error?.code));
      return;
    }

    pass(`Number reachable: ${String(payload.display_phone_number ?? "unknown")}`);
    if (payload.verified_name) pass(`Display name: ${String(payload.verified_name)}`);
    if (payload.quality_rating) pass(`Quality rating: ${String(payload.quality_rating)}`);

    // platform_type distinguishes a coexistence number from a plain Cloud API one.
    const platform = payload.platform_type;
    if (typeof platform === "string") {
      const coexisting = platform.toUpperCase().includes("SMB");
      console.log(`  ${coexisting ? tick : warn} platform_type: ${platform}`);
      if (!coexisting) {
        console.log(
          dim(
            "    → Not a coexistence number. The bot still works, but this number\n" +
              "      cannot also be used in the WhatsApp Business app, and\n" +
              "      smb_message_echoes will never fire.",
          ),
        );
        warnings += 1;
      }
    } else {
      caution(
        "Meta did not report platform_type",
        "Cannot confirm coexistence from here; check WhatsApp Manager.",
      );
    }
  } catch (error) {
    fail(`Could not reach Meta: ${(error as Error).message}`, "Check your network and try again.");
  }
}

function hintForGraphError(code: number | undefined): string {
  switch (code) {
    case 190:
      return "The access token is invalid or expired. The one on the API Setup screen lasts 24 hours — create a System User token for production.";
    case 100:
      return "Usually a wrong Phone number ID. Copy it from WhatsApp > API Setup — it is not your phone number.";
    case 10:
    case 200:
      return "The token lacks permissions. It needs whatsapp_business_messaging and whatsapp_business_management.";
    default:
      return "Check the token, the Phone number ID, and that the app has the WhatsApp product added.";
  }
}

/**
 * Tests a deployed webhook the way Meta does: the GET verification handshake,
 * then a correctly signed POST, then an unsigned one that must be rejected.
 * The POST body is a delivery-status callback, so nothing is sent to anyone.
 */
async function checkWebhook(baseUrl: string): Promise<void> {
  section(`Deployed webhook (${baseUrl})`);

  const verifyToken = process.env.WHATSAPP_VERIFY_TOKEN;
  const appSecret = process.env.WHATSAPP_APP_SECRET;
  if (!verifyToken || !appSecret) {
    fail("Cannot test — WHATSAPP_VERIFY_TOKEN or WHATSAPP_APP_SECRET missing");
    return;
  }

  const endpoint = `${baseUrl.replace(/\/+$/, "")}/webhook`;
  const challenge = crypto.randomUUID();

  try {
    const query = new URLSearchParams({
      "hub.mode": "subscribe",
      "hub.verify_token": verifyToken,
      "hub.challenge": challenge,
    });
    const response = await fetch(`${endpoint}?${query}`);
    const text = (await response.text()).trim();

    if (response.ok && text === challenge) {
      pass("Verification handshake succeeded — Meta will accept this URL");
    } else if (response.status === 403) {
      fail(
        "Server returned 403 to the handshake",
        "The running server's WHATSAPP_VERIFY_TOKEN differs from this machine's .env.",
      );
    } else {
      fail(`Handshake returned HTTP ${response.status} with body "${text.slice(0, 60)}"`,
        "Check the URL points at this bot and that /webhook is reachable.");
    }
  } catch (error) {
    fail(`Could not reach ${endpoint}: ${(error as Error).message}`,
      "Is the server running and the URL public? For local testing use ngrok.");
    return;
  }

  // A statuses-only payload: it exercises the signature path and returns 200
  // without the bot messaging anybody.
  const body = JSON.stringify({
    object: "whatsapp_business_account",
    entry: [
      {
        id: "doctor",
        changes: [
          {
            field: "messages",
            value: { statuses: [{ id: "wamid.doctor", status: "delivered" }] },
          },
        ],
      },
    ],
  });
  const signature = `sha256=${crypto.createHmac("sha256", appSecret).update(body).digest("hex")}`;

  try {
    const signed = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Hub-Signature-256": signature },
      body,
    });
    if (signed.ok) {
      pass("Signed webhook POST accepted");
    } else if (signed.status === 401) {
      fail(
        "Server rejected a correctly signed POST",
        "The running server's WHATSAPP_APP_SECRET differs from this machine's .env.",
      );
    } else {
      fail(`Signed POST returned HTTP ${signed.status}`);
    }

    const unsigned = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (unsigned.status === 401) {
      pass("Unsigned webhook POST rejected — forged requests cannot reach the bot");
    } else {
      fail(
        `Unsigned POST returned HTTP ${unsigned.status}, expected 401`,
        "Signature verification is not protecting this deployment.",
      );
    }
  } catch (error) {
    fail(`POST test failed: ${(error as Error).message}`);
  }
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      live: { type: "boolean", default: false },
      url: { type: "string" },
    },
    allowPositionals: false,
  });

  console.log(bold("\nWhatsApp bot setup check"));

  let config: BusinessConfig;
  try {
    config = loadBusinessConfig();
  } catch (error) {
    console.log(`\n  ${cross} ${(error as Error).message}`);
    process.exit(1);
  }

  checkBusinessConfig(config);
  checkRules(config);
  checkEnv(config);
  if (values.live) await checkLive();
  if (values.url) await checkWebhook(values.url);

  console.log(
    `\n${failures === 0 ? tick : cross} ${failures} problem(s), ${warnings} warning(s)\n`,
  );
  if (!values.live && !values.url) {
    console.log(
      dim(
        "Next: `npm run doctor -- --live` checks your number with Meta.\n" +
          "      `npm run doctor -- --url https://your-domain` tests a deployed webhook.\n",
      ),
    );
  }
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((error: Error) => {
  console.error(error.message);
  process.exit(1);
});
