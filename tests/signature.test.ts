import assert from "node:assert/strict";
import crypto from "node:crypto";
import { test } from "node:test";
import { verifySignature } from "../src/signature.js";

const secret = "test-app-secret";
const body = Buffer.from(JSON.stringify({ object: "whatsapp_business_account" }));
const valid = `sha256=${crypto.createHmac("sha256", secret).update(body).digest("hex")}`;

test("accepts a signature Meta would have produced", () => {
  assert.equal(verifySignature(body, valid, secret), true);
});

test("rejects a signature made with the wrong secret", () => {
  const forged = `sha256=${crypto.createHmac("sha256", "wrong").update(body).digest("hex")}`;
  assert.equal(verifySignature(body, forged, secret), false);
});

test("rejects a tampered body", () => {
  assert.equal(verifySignature(Buffer.from("{}"), valid, secret), false);
});

test("rejects missing or malformed headers", () => {
  assert.equal(verifySignature(body, undefined, secret), false);
  assert.equal(verifySignature(body, "sha1=abc", secret), false);
  assert.equal(verifySignature(body, "sha256=short", secret), false);
});
