/** Shared types for the WhatsApp auto-reply bot. */

/** One canned-reply rule, as authored in `config/business.json`. */
export interface Rule {
  /** Stable identifier, used in logs and tests. */
  id: string;
  /**
   * Words or phrases that trigger this rule. Single words match on word
   * boundaries ("hi" does not match "this"); multi-word phrases match as a
   * contiguous run of words.
   */
  keywords: string[];
  /** Optional extra regex (case-insensitive) that also triggers the rule. */
  regex?: string;
  /** Reply sent during business hours. Supports {{placeholder}} substitution. */
  reply: string;
  /** Reply sent outside business hours. Falls back to `reply` when absent. */
  afterHoursReply?: string;
  /** When true, matching this rule hands the chat over to a human. */
  handoff?: boolean;
  /**
   * Extra weight for tie-breaking. Rules score by matched keyword length;
   * priority is added on top. Default 0.
   */
  priority?: number;
}

/** A property the bot can answer questions about. */
export interface Listing {
  ref: string;
  title: string;
  type: string;
  area: string;
  price: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  tenure?: string;
  furnishing?: string;
  status: "available" | "under offer" | "sold" | "rented";
  highlights?: string[];
  notes?: string;
}

export interface FaqEntry {
  q: string;
  a: string;
}

/** `"09:00-19:00"`, or `null` for a closed day. */
export type DayHours = string | null;

export interface BusinessHours {
  mon: DayHours;
  tue: DayHours;
  wed: DayHours;
  thu: DayHours;
  fri: DayHours;
  sat: DayHours;
  sun: DayHours;
}

/** The whole editable business profile — `config/business.json`. */
export interface BusinessConfig {
  agentName: string;
  agency: string;
  /** IANA timezone, e.g. "Asia/Kuala_Lumpur". */
  timezone: string;
  businessHours: BusinessHours;
  languages: string[];
  serviceAreas: string[];
  /** Free-form extra context handed to Claude (specialities, fees, policies). */
  about: string;
  /** WhatsApp number (E.164, no +) that receives handoff alerts. Optional. */
  alertNumber?: string;
  signOff: string;
  listings: Listing[];
  faq: FaqEntry[];
  rules: Rule[];
  /** Sent when the bot receives a photo/voice note/document it cannot read. */
  unsupportedMediaReply: string;
  /** Sent once when a chat is handed to a human. */
  handoffReply: string;
  /** Sent when Claude is unavailable and no rule matched. */
  fallbackReply: string;
}

/** A normalised inbound WhatsApp message. */
export interface InboundMessage {
  /** Meta's message id (`wamid...`), used for de-duplication. */
  id: string;
  /** Sender's WhatsApp number in E.164 without the leading `+`. */
  from: string;
  /** WhatsApp profile name, when Meta supplies it. */
  profileName?: string;
  /** `text`, `image`, `audio`, `document`, `location`, ... */
  type: string;
  /** Message body — empty for non-text types. */
  text: string;
  /** Unix seconds. */
  timestamp: number;
}

/** What the bot decided to do about one inbound message. */
export interface Decision {
  /** Message to send, or null to stay silent. */
  reply: string | null;
  /** Where the reply came from. */
  source: "rule" | "claude" | "canned" | "none";
  /** Rule id, when `source` is "rule". */
  ruleId?: string;
  /** Hand this chat to a human and stop auto-replying. */
  handoff: boolean;
  /** Why the bot stayed silent, for the logs. */
  silentReason?: string;
  /** Lead details gathered from the conversation, if any. */
  lead?: LeadUpdate;
}

/** Lead qualification fields Claude extracts opportunistically. */
export interface LeadUpdate {
  name?: string;
  intent?: "buy" | "rent" | "sell" | "invest" | "unknown";
  propertyRef?: string;
  area?: string;
  budget?: string;
  timeline?: string;
  wantsViewing?: boolean;
}

/** Per-contact state, persisted across restarts. */
export interface ChatState {
  /** Rolling conversation history handed to Claude. */
  history: { role: "user" | "assistant"; content: string }[];
  /** Unix ms when a human took over; auto-replies pause until it expires. */
  handoffUntil?: number;
  /** Unix ms timestamps of auto-replies sent, for rate limiting. */
  replyTimes: number[];
  /** Accumulated lead details. */
  lead: LeadUpdate;
  profileName?: string;
  lastSeen: number;
}
