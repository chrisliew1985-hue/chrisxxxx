import assert from "node:assert/strict";
import { test } from "node:test";
import { parseEchoes, parseInbound } from "../src/whatsapp.js";

/** The shape Meta sends when the agent types in the WhatsApp Business app. */
const echoPayload = {
  object: "whatsapp_business_account",
  entry: [
    {
      id: "WABA_ID",
      changes: [
        {
          field: "smb_message_echoes",
          value: {
            messaging_product: "whatsapp",
            metadata: { display_phone_number: "60111111111", phone_number_id: "PNID" },
            message_echoes: [
              {
                from: "60111111111",
                to: "60123456789",
                id: "wamid.echo1",
                timestamp: "1781305966",
                type: "text",
                text: { body: "On my way, see you at 3." },
              },
            ],
          },
        },
      ],
    },
  ],
};

const inboundPayload = {
  object: "whatsapp_business_account",
  entry: [
    {
      id: "WABA_ID",
      changes: [
        {
          field: "messages",
          value: {
            contacts: [{ wa_id: "60123456789", profile: { name: "Aisyah" } }],
            messages: [
              {
                from: "60123456789",
                id: "wamid.in1",
                timestamp: "1781305900",
                type: "text",
                text: { body: "Is it still available?" },
              },
            ],
          },
        },
      ],
    },
  ],
};

test("an echo is parsed with the customer's number as the target", () => {
  const echoes = parseEchoes(echoPayload);
  assert.equal(echoes.length, 1);
  assert.deepEqual(echoes[0], {
    id: "wamid.echo1",
    to: "60123456789",
    type: "text",
    text: "On my way, see you at 3.",
    timestamp: 1781305966,
  });
});

test("an echo is never mistaken for an inbound customer message", () => {
  assert.deepEqual(parseInbound(echoPayload), []);
});

test("an inbound message is never mistaken for an echo", () => {
  assert.deepEqual(parseEchoes(inboundPayload), []);
  assert.equal(parseInbound(inboundPayload)[0]?.profileName, "Aisyah");
});

test("status callbacks and unknown fields are ignored by both parsers", () => {
  const statusOnly = {
    entry: [
      {
        changes: [
          { field: "messages", value: { statuses: [{ id: "wamid.x", status: "delivered" }] } },
        ],
      },
    ],
  };
  assert.deepEqual(parseInbound(statusOnly), []);
  assert.deepEqual(parseEchoes(statusOnly), []);
  assert.deepEqual(parseEchoes({}), []);
  assert.deepEqual(parseInbound({}), []);
});
