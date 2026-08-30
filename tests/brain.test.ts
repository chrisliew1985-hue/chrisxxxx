import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { commit, decide } from "../src/brain.js";
import { loadBusinessConfig } from "../src/config.js";
import { Store } from "../src/store.js";
import type { InboundMessage } from "../src/types.js";

const config = loadBusinessConfig("config/business.json");

function freshStore(): Store {
  return new Store(fs.mkdtempSync(path.join(os.tmpdir(), "wabot-")));
}

function inbound(text: string, overrides: Partial<InboundMessage> = {}): InboundMessage {
  return {
    id: `wamid.${Math.random()}`,
    from: "60123456789",
    profileName: "Aisyah",
    type: "text",
    text,
    timestamp: Math.floor(Date.now() / 1000),
    ...overrides,
  };
}

// Monday 12:00 and 23:00 in Kuala Lumpur (UTC+8).
const openHours = new Date("2026-08-31T04:00:00Z");
const closedHours = new Date("2026-08-31T15:00:00Z");

test("a greeting is answered from the rules, without calling Claude", async () => {
  const decision = await decide({
    config,
    store: freshStore(),
    message: inbound("Hi there"),
    now: openHours,
  });
  assert.equal(decision.source, "rule");
  assert.equal(decision.ruleId, "greeting");
  assert.match(decision.reply ?? "", /Chris/);
});

test("after hours a rule uses its after-hours wording", async () => {
  const decision = await decide({
    config,
    store: freshStore(),
    message: inbound("hello"),
    now: closedHours,
  });
  assert.match(decision.reply ?? "", /closed right now/);
});

test("asking for a real person triggers a handoff", async () => {
  const store = freshStore();
  const message = inbound("can I talk to a real person please");
  const decision = await decide({ config, store, message, now: openHours });
  assert.equal(decision.handoff, true);

  const result = commit({ store, message, decision, now: openHours });
  assert.ok(result.alert?.includes("needs you on WhatsApp"));
  assert.equal(store.isHandedOff(message.from), true);
});

test("once handed off the bot stays silent", async () => {
  const store = freshStore();
  const first = inbound("I want to speak to agent");
  commit({
    store,
    message: first,
    decision: await decide({ config, store, message: first, now: openHours }),
    now: openHours,
  });

  const second = await decide({ config, store, message: inbound("hello?"), now: openHours });
  assert.equal(second.reply, null);
  assert.equal(second.silentReason, "handed off to human");
});

test("clearing the handoff lets the bot answer again", async () => {
  const store = freshStore();
  const message = inbound("call me");
  commit({
    store,
    message,
    decision: await decide({ config, store, message, now: openHours }),
    now: openHours,
  });
  store.clearHandoff(message.from);

  const next = await decide({ config, store, message: inbound("hi"), now: openHours });
  assert.equal(next.source, "rule");
});

test("photos and voice notes get the unsupported-media reply", async () => {
  const decision = await decide({
    config,
    store: freshStore(),
    message: inbound("", { type: "image" }),
    now: openHours,
  });
  assert.equal(decision.source, "canned");
  assert.match(decision.reply ?? "", /only read text messages/);
});

test("with no Claude key an unmatched message falls back and hands over", async () => {
  assert.equal(process.env.ANTHROPIC_API_KEY, undefined, "test must run without an API key");
  const decision = await decide({
    config,
    store: freshStore(),
    message: inbound("what is the maintenance fee per square foot on the high floors"),
    now: openHours,
  });
  assert.equal(decision.source, "canned");
  assert.equal(decision.handoff, true);
});

test("the hourly cap silences the bot before it can spam a contact", async () => {
  const store = freshStore();
  const cap = Number(process.env.MAX_REPLIES_PER_HOUR ?? 12);

  for (let index = 0; index < cap; index += 1) {
    const message = inbound("hi");
    commit({
      store,
      message,
      decision: await decide({ config, store, message, now: openHours }),
      now: openHours,
    });
  }
  const capped = await decide({ config, store, message: inbound("hi"), now: openHours });
  assert.equal(capped.reply, null);
  assert.equal(capped.silentReason, "hourly reply cap");
});

test("a repeated webhook delivery is only handled once", () => {
  const store = freshStore();
  assert.equal(store.markSeen("wamid.abc"), true);
  assert.equal(store.markSeen("wamid.abc"), false);
});

test("history is capped so the prompt cannot grow without bound", () => {
  const store = freshStore();
  const turns = Number(process.env.HISTORY_TURNS ?? 12);
  for (let index = 0; index < turns + 5; index += 1) {
    store.appendHistory("60123456789", "user", `message ${index}`);
    store.appendHistory("60123456789", "assistant", `reply ${index}`);
  }
  assert.equal(store.getChat("60123456789").history.length, turns * 2);
});

test("state survives a restart", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wabot-"));
  const first = new Store(dir);
  first.startHandoff("60123456789", 1);
  first.markSeen("wamid.persisted");
  first.flush();

  const second = new Store(dir);
  assert.equal(second.isHandedOff("60123456789"), true);
  assert.equal(second.markSeen("wamid.persisted"), false);
});

test("a shorter pause never cuts a longer handoff short", () => {
  const store = freshStore();
  const now = Date.now();
  store.startHandoff("60123456789", 12, now);
  store.startHandoff("60123456789", 4, now);
  // Still paused 11 hours from now, i.e. the 12-hour handoff survived.
  assert.equal(store.isHandedOff("60123456789", now + 11 * 60 * 60 * 1000), true);
});

test("a longer pause does extend a shorter one", () => {
  const store = freshStore();
  const now = Date.now();
  store.startHandoff("60123456789", 4, now);
  store.startHandoff("60123456789", 12, now);
  assert.equal(store.isHandedOff("60123456789", now + 11 * 60 * 60 * 1000), true);
});
