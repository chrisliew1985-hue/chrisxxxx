import assert from "node:assert/strict";
import { test } from "node:test";
import { describeBusinessHours, isWithinBusinessHours } from "../src/hours.js";
import type { BusinessConfig } from "../src/types.js";

const config = {
  timezone: "Asia/Kuala_Lumpur",
  businessHours: {
    mon: "09:00-19:00",
    tue: "09:00-19:00",
    wed: "09:00-19:00",
    thu: "09:00-19:00",
    fri: "09:00-19:00",
    sat: "10:00-17:00",
    sun: null,
  },
} as unknown as BusinessConfig;

// Kuala Lumpur is UTC+8, so 04:00Z is 12:00 local.
test("midday on a weekday is inside business hours", () => {
  assert.equal(isWithinBusinessHours(config, new Date("2026-08-31T04:00:00Z")), true);
});

test("late evening is outside business hours", () => {
  assert.equal(isWithinBusinessHours(config, new Date("2026-08-31T14:00:00Z")), false);
});

test("a closed day is always outside business hours", () => {
  assert.equal(isWithinBusinessHours(config, new Date("2026-08-30T04:00:00Z")), false);
});

test("the closing minute itself is already closed", () => {
  // Saturday 17:00 local.
  assert.equal(isWithinBusinessHours(config, new Date("2026-08-29T09:00:00Z")), false);
  // Saturday 16:59 local.
  assert.equal(isWithinBusinessHours(config, new Date("2026-08-29T08:59:00Z")), true);
});

test("overnight ranges wrap past midnight", () => {
  const nightShift = {
    timezone: "UTC",
    businessHours: {
      mon: "18:00-02:00",
      tue: "18:00-02:00",
      wed: null,
      thu: null,
      fri: null,
      sat: null,
      sun: null,
    },
  } as unknown as BusinessConfig;
  assert.equal(isWithinBusinessHours(nightShift, new Date("2026-08-31T20:00:00Z")), true);
  assert.equal(isWithinBusinessHours(nightShift, new Date("2026-09-01T01:00:00Z")), true);
  assert.equal(isWithinBusinessHours(nightShift, new Date("2026-09-01T03:00:00Z")), false);
});

test("consecutive identical days are grouped for readability", () => {
  assert.equal(
    describeBusinessHours(config),
    "Mon-Fri 09:00-19:00, Sat 10:00-17:00, Sun closed",
  );
});

test("a single open day is not rendered as a range", () => {
  const weekendOnly = {
    timezone: "UTC",
    businessHours: {
      mon: null,
      tue: null,
      wed: null,
      thu: null,
      fri: null,
      sat: "10:00-14:00",
      sun: null,
    },
  } as unknown as BusinessConfig;
  assert.equal(describeBusinessHours(weekendOnly), "Mon-Fri closed, Sat 10:00-14:00, Sun closed");
});
