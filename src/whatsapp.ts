import { env } from "./config.js";
import { log, maskNumber, redactBody } from "./logger.js";
import type { InboundMessage } from "./types.js";

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
export async function sendText(to: string, body: string): Promise<void> {
  const trimmed = body.length > MAX_BODY_LENGTH ? `${body.slice(0, MAX_BODY_LENGTH - 1)}…` : body;
  await callGraph(`${env.phoneNumberId}/messages`, {
    messaging_product: "whatsapp",
    recipient_type: "individual",
    to,
    type: "text",
    text: { preview_url: false, body: trimmed },
  });
  log.info("Sent reply", { to: maskNumber(to), body: redactBody(trimmed) });
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

interface WebhookPayload {
  entry?: {
    changes?: {
      value?: { contacts?: RawContact[]; messages?: RawMessage[] };
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
