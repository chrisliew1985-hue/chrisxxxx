/**
 * Chat with the bot in your terminal — no Meta app, no webhook, no phone.
 * Run with `npm run dry-run`. Replies come from the same code path the real
 * webhook uses, so what you see here is what a customer would get.
 *
 * Commands: /reset clears the conversation, /quit exits.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { commit, decide } from "./brain.js";
import { isClaudeEnabled } from "./claude.js";
import { loadBusinessConfig } from "./config.js";
import { isWithinBusinessHours } from "./hours.js";
import { Store } from "./store.js";
import type { InboundMessage } from "./types.js";

const config = loadBusinessConfig();
// A throwaway directory keeps dry runs out of your real conversation state.
let store = new Store(fs.mkdtempSync(path.join(os.tmpdir(), "wabot-dryrun-")));

const FROM = "60100000000";
const PROFILE = "Dry Run";

const dim = (text: string) => `[2m${text}[0m`;
const green = (text: string) => `[32m${text}[0m`;

async function main(): Promise<void> {
  const open = isWithinBusinessHours(config);
  console.log(`\n${config.agency} — ${config.agentName}'s WhatsApp assistant (dry run)`);
  console.log(
    dim(
      `Claude: ${isClaudeEnabled() ? "on" : "off (no ANTHROPIC_API_KEY — rules only)"} · ` +
        `${config.rules.length} rules · ${config.listings.length} listings · ` +
        `currently ${open ? "open" : "closed"}`,
    ),
  );
  console.log(dim("Type a customer message. /reset to start over, /quit to exit.\n"));

  // The async line iterator (rather than repeated rl.question) keeps piped
  // input working, so you can script a conversation as well as type one.
  const rl = readline.createInterface({ input: stdin, output: stdout });
  rl.setPrompt("customer > ");
  rl.prompt();

  for await (const line of rl) {
    const text = line.trim();
    if (text === "/quit") break;
    if (!text) {
      rl.prompt();
      continue;
    }
    if (text === "/reset") {
      store = new Store(fs.mkdtempSync(path.join(os.tmpdir(), "wabot-dryrun-")));
      console.log(dim("conversation reset\n"));
      rl.prompt();
      continue;
    }

    const message: InboundMessage = {
      id: `dryrun.${Date.now()}.${Math.random()}`,
      from: FROM,
      profileName: PROFILE,
      type: "text",
      text,
      timestamp: Math.floor(Date.now() / 1000),
    };

    const decision = await decide({ config, store, message });
    const result = commit({ store, message, decision });

    if (result.reply) {
      console.log(`${green("bot")}      > ${result.reply}`);
    } else {
      console.log(dim(`(silent — ${result.silentReason ?? "no reply"})`));
    }
    const tags = [
      `via ${result.source}${result.ruleId ? `:${result.ruleId}` : ""}`,
      result.handoff ? "HANDOFF" : null,
    ].filter(Boolean);
    console.log(dim(`           ${tags.join(" · ")}`));
    if (result.alert) {
      console.log(dim(`\n--- alert to ${config.agentName} ---\n${result.alert}\n---`));
    }
    console.log();
    rl.prompt();
  }

  rl.close();
  console.log(dim("bye\n"));
}

main().catch((error: Error) => {
  console.error(error.message);
  process.exit(1);
});
