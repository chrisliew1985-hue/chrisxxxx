import assert from "node:assert/strict";
import { test } from "node:test";
import { matchRule, normalise, render, templateValues } from "../src/rules.js";
import type { BusinessConfig, Rule } from "../src/types.js";

const rules: Rule[] = [
  { id: "greeting", keywords: ["hi", "hello", "你好"], reply: "Hi there" },
  {
    id: "viewing",
    keywords: ["book a viewing", "view"],
    reply: "Let's arrange it",
    afterHoursReply: "Tomorrow then",
    priority: 2,
  },
  { id: "human", keywords: ["real person"], reply: "Passing you over", handoff: true },
  { id: "price", keywords: [], regex: "rm\\s?\\d{3,}", reply: "About the price" },
];

test("word boundaries stop short keywords matching inside longer words", () => {
  assert.equal(matchRule("this is the thing", rules), null);
  assert.equal(matchRule("hi", rules)?.rule.id, "greeting");
});

test("the longest keyword hit wins over a shorter one", () => {
  const match = matchRule("hi, can I book a viewing please", rules);
  assert.equal(match?.rule.id, "viewing");
});

test("non-Latin keywords match without word boundaries", () => {
  assert.equal(matchRule("你好，我想问一下", rules)?.rule.id, "greeting");
});

test("a rule regex matches even with no keyword hits", () => {
  const match = matchRule("is it still RM780000?", rules);
  assert.equal(match?.rule.id, "price");
});

test("unmatched text returns null so Claude can take over", () => {
  assert.equal(matchRule("what is the maintenance fee per square foot", rules), null);
});

test("empty and punctuation-only messages never match", () => {
  assert.equal(matchRule("", rules), null);
  assert.equal(matchRule("???", rules), null);
});

test("normalise strips punctuation and collapses whitespace", () => {
  assert.equal(normalise("  Hello,   THERE!! "), "hello there");
});

const config = {
  agentName: "Chris",
  agency: "Acme Realty",
  timezone: "Asia/Kuala_Lumpur",
  businessHours: {
    mon: "09:00-19:00",
    tue: null,
    wed: null,
    thu: null,
    fri: null,
    sat: null,
    sun: null,
  },
  languages: ["English"],
  serviceAreas: ["Bangsar", "KLCC"],
  signOff: "— Chris",
} as unknown as BusinessConfig;

test("placeholders resolve from the business config", () => {
  const values = templateValues(config, { name: "Aisyah" });
  assert.equal(render("Hi {{name}}, {{agentName}} covers {{areas}}.", values), "Hi Aisyah, Chris covers Bangsar, KLCC.");
});

test("unknown placeholders are dropped, never shown to the customer", () => {
  const rendered = render("Hello {{nope}} there, from {{agentName}}", templateValues(config));
  assert.ok(!rendered.includes("{{"));
  assert.equal(rendered, "Hello there, from Chris");
});
