import { env } from "./config.js";
import { generateReply, isClaudeEnabled } from "./claude.js";
import { isWithinBusinessHours } from "./hours.js";
import { log, maskNumber } from "./logger.js";
import { matchRule, render, templateValues } from "./rules.js";
import type { Store } from "./store.js";
import type { BusinessConfig, Decision, InboundMessage } from "./types.js";

/** Message types the bot cannot read, so it acknowledges them instead. */
const UNREADABLE_TYPES = new Set([
  "image",
  "audio",
  "video",
  "document",
  "sticker",
  "location",
  "contacts",
  "unsupported",
]);

export interface DecideOptions {
  config: BusinessConfig;
  store: Store;
  message: InboundMessage;
  now?: Date;
}

/**
 * Decides what to send back for one inbound message. Pure with respect to the
 * network — it reads and writes the store but never sends anything itself, so
 * the whole decision path is testable without hitting Meta or Anthropic.
 */
export async function decide(options: DecideOptions): Promise<Decision> {
  const { config, store, message } = options;
  const now = options.now ?? new Date();
  const withinHours = isWithinBusinessHours(config, now);
  const chat = store.getChat(message.from);

  if (message.profileName && chat.profileName !== message.profileName) {
    store.updateChat(message.from, (state) => {
      state.profileName = message.profileName;
    });
  }

  // A human has taken this chat over; the bot stays out of the way.
  if (store.isHandedOff(message.from, now.getTime())) {
    return { reply: null, source: "none", handoff: true, silentReason: "handed off to human" };
  }

  // Guards against a loop or an abusive sender burning through the API budget.
  if (!store.canReply(message.from, now.getTime())) {
    return { reply: null, source: "none", handoff: false, silentReason: "hourly reply cap" };
  }

  const values = templateValues(config, { name: message.profileName });

  if (UNREADABLE_TYPES.has(message.type) || !message.text) {
    return {
      reply: render(config.unsupportedMediaReply, values),
      source: "canned",
      handoff: false,
    };
  }

  const match = matchRule(message.text, config.rules);
  if (match) {
    const template =
      !withinHours && match.rule.afterHoursReply ? match.rule.afterHoursReply : match.rule.reply;
    log.info("Rule matched", {
      from: maskNumber(message.from),
      rule: match.rule.id,
      score: match.score,
      matched: match.matched,
    });
    return {
      reply: render(template, values),
      source: "rule",
      ruleId: match.rule.id,
      handoff: match.rule.handoff === true,
    };
  }

  if (!isClaudeEnabled()) {
    return { reply: render(config.fallbackReply, values), source: "canned", handoff: true };
  }

  const generated = await generateReply({
    config,
    chat,
    message: message.text,
    profileName: message.profileName,
    withinHours,
  });

  if (!generated) {
    // Claude is unreachable or declined — never leave the customer on read.
    return { reply: render(config.fallbackReply, values), source: "canned", handoff: true };
  }

  if (generated.handoff && generated.handoffReason) {
    log.info("Claude requested handoff", {
      from: maskNumber(message.from),
      reason: generated.handoffReason,
    });
  }

  return {
    reply: generated.reply || render(config.handoffReply, values),
    source: "claude",
    handoff: generated.handoff,
    lead: generated.lead,
  };
}

export interface HandleResult extends Decision {
  /** The alert to send to the agent's own number, if one is warranted. */
  alert?: string;
}

/**
 * Applies a decision to the store: records history, the lead, the reply budget
 * and the handoff pause, and composes the agent alert. Sending is the caller's
 * job so this stays testable.
 */
export function commit(options: {
  store: Store;
  message: InboundMessage;
  decision: Decision;
  now?: Date;
}): HandleResult {
  const { store, message, decision } = options;
  const now = (options.now ?? new Date()).getTime();
  const result: HandleResult = { ...decision };

  if (decision.lead) {
    const lead = store.mergeLead(message.from, decision.lead);
    if (lead.wantsViewing || lead.budget || lead.propertyRef) {
      store.recordLead(message.from, lead, message.profileName);
    }
  }

  if (decision.reply === null) return result;

  // Media messages carry no text; an empty user turn would only confuse Claude.
  if (message.text) {
    store.appendHistory(message.from, "user", message.text);
    store.appendHistory(message.from, "assistant", decision.reply);
  }
  store.recordReply(message.from, now);

  if (decision.handoff && !store.isHandedOff(message.from, now)) {
    store.startHandoff(message.from, env.handoffHours, now);
    const chat = store.getChat(message.from);
    const who = message.profileName ?? message.from;
    const known = Object.entries(chat.lead)
      .filter(([, value]) => value !== undefined && value !== "unknown")
      .map(([key, value]) => `${key}: ${value}`)
      .join(", ");
    result.alert =
      `🔔 ${who} (+${message.from}) needs you on WhatsApp.\n` +
      `They said: "${message.text.slice(0, 300)}"\n` +
      (known ? `What we know: ${known}\n` : "") +
      `Auto-replies are paused for this chat for ${env.handoffHours}h.`;
  }

  return result;
}
