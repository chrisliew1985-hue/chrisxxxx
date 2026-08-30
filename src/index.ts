import express, { type Request, type Response } from "express";
import { commit, decide } from "./brain.js";
import { env, loadBusinessConfig, validateEnv } from "./config.js";
import { isClaudeEnabled } from "./claude.js";
import { log, maskNumber, redactBody } from "./logger.js";
import { verifySignature } from "./signature.js";
import { Store } from "./store.js";
import { markRead, parseEchoes, parseInbound, sendText } from "./whatsapp.js";
import type { BusinessConfig, EchoMessage, InboundMessage } from "./types.js";

declare module "express-serve-static-core" {
  interface Request {
    /** Raw request body, needed to verify Meta's HMAC signature. */
    rawBody?: Buffer;
  }
}

validateEnv();
const config: BusinessConfig = loadBusinessConfig();
const store = new Store();
const app = express();

app.use(
  express.json({
    // The signature covers the exact bytes Meta sent, so keep them before parsing.
    verify: (req: Request, _res, buffer) => {
      req.rawBody = Buffer.from(buffer);
    },
  }),
);

app.get("/health", (_req, res) => {
  res.json({ ok: true, claude: isClaudeEnabled(), rules: config.rules.length });
});

/** Meta calls this once when you register the webhook URL. */
app.get("/webhook", (req: Request, res: Response) => {
  const mode = req.query["hub.mode"];
  const token = req.query["hub.verify_token"];
  const challenge = req.query["hub.challenge"];

  if (mode === "subscribe" && token === env.verifyToken && typeof challenge === "string") {
    log.info("Webhook verified by Meta");
    res.status(200).send(challenge);
    return;
  }
  log.warn("Webhook verification failed", { mode });
  res.sendStatus(403);
});

app.post("/webhook", (req: Request, res: Response) => {
  if (!verifySignature(req.rawBody ?? Buffer.alloc(0), req.get("x-hub-signature-256"), env.appSecret)) {
    log.warn("Rejected webhook with a bad signature");
    res.sendStatus(401);
    return;
  }

  // Meta retries the whole delivery unless it gets a fast 200, so acknowledge
  // first and do the work afterwards.
  res.sendStatus(200);

  // In coexistence mode Meta also echoes what the agent typed on their phone.
  for (const echo of parseEchoes(req.body)) {
    handleEcho(echo);
  }
  for (const message of parseInbound(req.body)) {
    void handleMessage(message);
  }
});

/**
 * The agent answered this customer by hand from the WhatsApp Business app, so
 * the bot backs off rather than talking over them. Each manual reply extends
 * the pause; it lapses on its own so the bot resumes without being told.
 */
function handleEcho(echo: EchoMessage): void {
  // Messages the bot itself sent are already marked seen, so they never
  // reach here and cannot make the bot pause itself.
  if (!store.markSeen(echo.id)) return;

  store.startHandoff(echo.to, env.manualReplyPauseHours);
  if (echo.text) {
    // Keep the manual reply in history so Claude has the thread if it resumes.
    store.appendHistory(echo.to, "assistant", echo.text);
  }
  log.info("Agent replied by hand, pausing auto-replies for this chat", {
    to: maskNumber(echo.to),
    hours: env.manualReplyPauseHours,
  });
}

async function handleMessage(message: InboundMessage): Promise<void> {
  if (!store.markSeen(message.id)) {
    log.info("Ignoring duplicate webhook delivery", { id: message.id });
    return;
  }

  log.info("Inbound message", {
    from: maskNumber(message.from),
    type: message.type,
    body: redactBody(message.text),
  });

  try {
    // Blue ticks are cosmetic — a failure here must not block the reply.
    await markRead(message.id).catch((error: Error) =>
      log.warn("Could not mark message read", { error: error.message }),
    );

    const decision = await decide({ config, store, message });
    const result = commit({ store, message, decision });

    if (result.reply) {
      const sentId = await sendText(message.from, result.reply);
      // Claim our own id up front: in coexistence mode this message may echo
      // back, and we must not mistake it for the agent typing.
      if (sentId) store.markSeen(sentId);
    } else {
      log.info("Staying silent", {
        from: maskNumber(message.from),
        reason: result.silentReason,
      });
    }

    if (result.alert && config.alertNumber) {
      await sendText(config.alertNumber, result.alert)
        .then((sentId) => {
          if (sentId) store.markSeen(sentId);
        })
        .catch((error: Error) =>
          log.error("Could not deliver handoff alert", { error: error.message }),
        );
    }
  } catch (error) {
    log.error("Failed to handle message", {
      from: maskNumber(message.from),
      error: (error as Error).message,
    });
  }
}

const server = app.listen(env.port, () => {
  log.info("WhatsApp auto-reply bot listening", {
    port: env.port,
    claude: isClaudeEnabled() ? env.model : "disabled (no ANTHROPIC_API_KEY)",
    rules: config.rules.length,
    listings: config.listings.length,
  });
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    log.info("Shutting down", { signal });
    server.close(() => {
      store.flush();
      process.exit(0);
    });
  });
}
