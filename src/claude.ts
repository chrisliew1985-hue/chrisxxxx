import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { z } from "zod";
import { env } from "./config.js";
import { describeBusinessHours } from "./hours.js";
import { log } from "./logger.js";
import type { BusinessConfig, ChatState, LeadUpdate } from "./types.js";

/** What Claude must return for every message it handles. */
const ReplySchema = z.object({
  reply: z
    .string()
    .describe("The WhatsApp message to send back. Empty string if a human must answer instead."),
  handoff: z
    .boolean()
    .describe("True when a human agent should take over this conversation."),
  handoff_reason: z
    .string()
    .describe("Short note for the agent explaining why, or an empty string."),
  lead: z.object({
    name: z.string().describe("Customer's name if they gave one, else empty string."),
    intent: z.enum(["buy", "rent", "sell", "invest", "unknown"]),
    propertyRef: z.string().describe("Listing ref they asked about, else empty string."),
    area: z.string().describe("Area or neighbourhood of interest, else empty string."),
    budget: z.string().describe("Stated budget, else empty string."),
    timeline: z.string().describe("When they want to move or transact, else empty string."),
    wantsViewing: z.boolean().describe("True if they asked to view a property."),
  }),
});

export interface ClaudeReply {
  reply: string;
  handoff: boolean;
  handoffReason: string;
  lead: LeadUpdate;
}

let client: Anthropic | null = null;

/** Null when no API key is set — the bot then runs on rules alone. */
function getClient(): Anthropic | null {
  if (!env.anthropicApiKey) return null;
  client ??= new Anthropic({ apiKey: env.anthropicApiKey });
  return client;
}

export function isClaudeEnabled(): boolean {
  return getClient() !== null;
}

function formatListings(config: BusinessConfig): string {
  const active = config.listings.filter((listing) => listing.status === "available");
  if (active.length === 0) return "No listings are currently loaded.";

  return active
    .map((listing) => {
      const specs = [
        listing.beds !== undefined ? `${listing.beds} bed` : null,
        listing.baths !== undefined ? `${listing.baths} bath` : null,
        listing.sqft !== undefined ? `${listing.sqft} sqft` : null,
        listing.tenure,
        listing.furnishing,
      ]
        .filter(Boolean)
        .join(", ");
      const highlights = listing.highlights?.length
        ? ` Highlights: ${listing.highlights.join("; ")}.`
        : "";
      const notes = listing.notes ? ` Notes: ${listing.notes}` : "";
      return `- [${listing.ref}] ${listing.title} — ${listing.type} in ${listing.area}, ${listing.price}${
        specs ? ` (${specs})` : ""
      }.${highlights}${notes}`;
    })
    .join("\n");
}

/**
 * Built once per request but deliberately stable: everything volatile (the
 * customer's name, whether we're open right now) goes in the user turn so the
 * cached prefix survives between messages.
 */
function buildSystemPrompt(config: BusinessConfig): string {
  const faq = config.faq.map((entry) => `Q: ${entry.q}\nA: ${entry.a}`).join("\n\n");

  return `You are the WhatsApp assistant for ${config.agentName}, a property agent at ${config.agency}.
You reply to property enquiries on WhatsApp on ${config.agentName}'s behalf.

## How to write
- Write like a real agent texting on WhatsApp: warm, direct, 1-3 short sentences.
- Never use markdown. WhatsApp shows *bold* with single asterisks; use it sparingly.
- Reply in the language the customer used. You can handle: ${config.languages.join(", ")}.
- Ask at most one question per message, and only when it moves the enquiry forward.
- Never invent a property, price, floor plan, availability, or appointment time.
- If you do not know something, say you will check and hand over to ${config.agentName}.

## Never do
- Never give legal, tax, valuation or loan-approval advice — hand over instead.
- Never promise a price, discount, or that an offer is accepted.
- Never confirm a viewing slot as booked. You may collect a preferred time and say
  ${config.agentName} will confirm it.
- Never share another customer's details.

## Hand over to a human (set handoff true) when
- The customer asks to speak to a person, or is upset or complaining.
- They make an offer, discuss a deposit, contract, or anything to be signed.
- They ask something outside these listings and FAQs that you cannot answer.
- The conversation needs a decision only ${config.agentName} can make.
When you set handoff true, still write a short holding reply that tells them
${config.agentName} will follow up personally.

## Business
Areas covered: ${config.serviceAreas.join(", ")}
Opening hours (${config.timezone}): ${describeBusinessHours(config)}
About: ${config.about}

## Current listings
${formatListings(config)}

## FAQ
${faq}

Sign off only when it reads naturally, using: ${config.signOff}`;
}

export interface ClaudeRequest {
  config: BusinessConfig;
  chat: ChatState;
  message: string;
  profileName?: string;
  withinHours: boolean;
}

/**
 * Asks Claude for a reply. Returns null on any API failure so the caller can
 * fall back to a canned message rather than leaving the customer on read.
 */
export async function generateReply(request: ClaudeRequest): Promise<ClaudeReply | null> {
  const anthropic = getClient();
  if (!anthropic) return null;

  const { config, chat, message, profileName, withinHours } = request;
  const context = [
    profileName ? `Customer's WhatsApp name: ${profileName}` : null,
    withinHours
      ? "It is currently inside business hours."
      : "It is currently outside business hours — do not promise an immediate call back.",
    Object.keys(chat.lead).length > 0
      ? `What we already know about this customer: ${JSON.stringify(chat.lead)}`
      : null,
  ]
    .filter(Boolean)
    .join("\n");

  try {
    const response = await anthropic.beta.messages.parse({
      model: env.model,
      max_tokens: 2000,
      // Chat replies are short and latency-sensitive; low effort is plenty.
      output_config: { effort: "low", format: zodOutputFormat(ReplySchema) },
      // Server-side fallback keeps the bot answering if a safety classifier
      // declines the request instead of returning a refusal the customer sees.
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: [
        {
          type: "text",
          text: buildSystemPrompt(config),
          cache_control: { type: "ephemeral" },
        },
      ],
      messages: [
        ...chat.history,
        { role: "user" as const, content: `${context}\n\nCustomer says:\n${message}`.trim() },
      ],
    });

    if (response.stop_reason === "refusal") {
      log.warn("Claude declined to answer this message", {
        category: response.stop_details?.category ?? null,
      });
      return null;
    }

    const parsed = response.parsed_output;
    if (!parsed) {
      log.warn("Claude returned no parsable output");
      return null;
    }

    return {
      reply: parsed.reply.trim(),
      handoff: parsed.handoff,
      handoffReason: parsed.handoff_reason,
      lead: {
        name: parsed.lead.name || undefined,
        intent: parsed.lead.intent,
        propertyRef: parsed.lead.propertyRef || undefined,
        area: parsed.lead.area || undefined,
        budget: parsed.lead.budget || undefined,
        timeline: parsed.lead.timeline || undefined,
        wantsViewing: parsed.lead.wantsViewing,
      },
    };
  } catch (error) {
    if (error instanceof Anthropic.RateLimitError) {
      log.warn("Claude rate limited", { error: error.message });
    } else if (error instanceof Anthropic.APIConnectionError) {
      log.warn("Could not reach the Claude API", { error: error.message });
    } else if (error instanceof Anthropic.APIError) {
      log.error("Claude API error", { status: error.status, error: error.message });
    } else {
      log.error("Unexpected error generating reply", { error: (error as Error).message });
    }
    return null;
  }
}
