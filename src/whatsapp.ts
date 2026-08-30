import { env } from "./config.js";
import { log, maskNumber, redactBody } from "./logger.js";
import type { EchoMessage, InboundMessage } from "./types.js";

const GRAPH_BASE = "https://graph.facebook.com";

/** Meta rejects text messages over 4096 characters. */
const MAX_BODY_LENGTH = 4096;

async function callGraph(pathname: string, body: unknown): Promise<unknown> {
  const response = await fetch(`${GRAPH_BASE}/${env.graphVersion}/${pathname}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Graph API ${response.status}: ${text}`);
  }
  return text ? JSON.parse(text) : {};
}

/**
 * Sends a plain text reply. Only valid inside the 24-hour customer service
 * window, which every reply to an inbound message is by definition.
 */
export async function sendText(to: string, body: string): Promise<string | null> {
  const trimmed = body.length > MAX_BODY_LENGTH ? `${body.slice(0, MAX_BODY_LENGTH - 1)}…` : body;
  const response = (await callGraph(`${env.phoneNumberId}/messages`, {
    messaging_product: "whatsapp",
    recipient_type: "individual",
    to,
    type: "text",
    text: { preview_url: false, body: trimmed },
  })) as { messages?: { id?: string }[] };

  log.info("Sent reply", { to: maskNumber(to), body: redactBody(trimmed) });
  // The id lets the caller recognise this message if it echoes back.
  return response.messages?.[0]?.id ?? null;
}

/** Shows the blue ticks so the customer knows the message landed. */
export async function markRead(messageId: string): Promise<void> {
  await callGraph(`${env.phoneNumberId}/messages`, {
    messaging_product: "whatsapp",
    status: "read",
    message_id: messageId,
  });
}

/** Minimal shape of one inbound message; Meta sends more fields than we read. */
interface RawMessage {
  id?: string;
  from?: string;
  type?: string;
  timestamp?: string;
  text?: { body?: string };
  button?: { text?: string };
  interactive?: {
    button_reply?: { title?: string };
    list_reply?: { title?: string };
  };
}

interface RawContact {
  wa_id?: string;
  profile?: { name?: string };
}

/** An echoed message carries `to` (the customer) rather than `from`. */
interface RawEcho extends RawMessage {
  to?: string;
}

interface WebhookPayload {
  entry?: {
    changes?: {
      field?: string;
      value?: {
        contacts?: RawContact[];
        messages?: RawMessage[];
        message_echoes?: RawEcho[];
      };
    }[];
  }[];
}

/** Pulls the text out of whichever field this message type uses. */
function extractText(message: RawMessage): string {
  return (
    message.text?.body ??
    message.button?.text ??
    message.interactive?.button_reply?.title ??
    message.interactive?.list_reply?.title ??
    ""
  ).trim();
}

/**
 * Flattens Meta's nested webhook envelope into a list of messages. Status
 * callbacks (delivered/read receipts) carry no `messages` array and are ignored.
 */
export function parseInbound(payload: unknown): InboundMessage[] {
  const body = payload as WebhookPayload;
  const results: InboundMessage[] = [];

  for (const entry of body.entry ?? []) {
    for (const change of entry.changes ?? []) {
      const value = change.value;
      if (!value?.messages) continue;

      const names = new Map<string, string>();
      for (const contact of value.contacts ?? []) {
        if (contact.wa_id && contact.profile?.name) {
          names.set(contact.wa_id, contact.profile.name);
        }
      }

      for (const message of value.messages) {
        if (!message.id || !message.from) continue;
        results.push({
          id: message.id,
          from: message.from,
          profileName: names.get(message.from),
          type: message.type ?? "unknown",
          text: extractText(message),
          timestamp: Number(message.timestamp ?? 0),
        });
      }
    }
  }
  return results;
}

/**
 * Extracts messages the agent sent by hand from the WhatsApp Business app.
 * Meta delivers these under the `smb_message_echoes` field once the number is
 * onboarded in coexistence mode; they are how the bot knows to step aside.
 */
export function parseEchoes(payload: unknown): EchoMessage[] {
  const body = payload as WebhookPayload;
  const results: EchoMessage[] = [];

  for (const entry of body.entry ?? []) {
    for (const change of entry.changes ?? []) {
      if (change.field !== "smb_message_echoes") continue;

      for (const echo of change.value?.message_echoes ?? []) {
        if (!echo.id || !echo.to) continue;
        results.push({
          id: echo.id,
          to: echo.to,
          type: echo.type ?? "unknown",
          text: extractText(echo),
          timestamp: Number(echo.timestamp ?? 0),
        });
      }
    }
  }
  return results;
}
