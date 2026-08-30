import fs from "node:fs";
import path from "node:path";
import { env } from "./config.js";
import { log } from "./logger.js";
import type { ChatState, LeadUpdate } from "./types.js";

interface PersistedState {
  chats: Record<string, ChatState>;
  /** Meta message id -> unix ms first seen. Guards against webhook retries. */
  seen: Record<string, number>;
}

const SEEN_TTL_MS = 24 * 60 * 60 * 1000;
const CHAT_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;

/**
 * File-backed store. A JSON file is plenty for one agent's inbox and keeps the
 * bot deployable without a database; swap the read/write pair for Redis or
 * Postgres if you ever run more than one instance.
 */
export class Store {
  private state: PersistedState = { chats: {}, seen: {} };
  private readonly statePath: string;
  private readonly leadsPath: string;
  private writeTimer: NodeJS.Timeout | null = null;

  constructor(dataDir = env.dataDir) {
    this.statePath = path.resolve(dataDir, "state.json");
    this.leadsPath = path.resolve(dataDir, "leads.jsonl");
    fs.mkdirSync(path.dirname(this.statePath), { recursive: true });
    this.load();
  }

  private load(): void {
    if (!fs.existsSync(this.statePath)) return;
    try {
      const parsed = JSON.parse(fs.readFileSync(this.statePath, "utf8")) as PersistedState;
      this.state = { chats: parsed.chats ?? {}, seen: parsed.seen ?? {} };
      this.prune();
    } catch (error) {
      // A corrupt state file must not stop the bot from answering customers.
      log.error("Could not read state file, starting empty", {
        path: this.statePath,
        error: (error as Error).message,
      });
    }
  }

  private prune(): void {
    const now = Date.now();
    for (const [id, seenAt] of Object.entries(this.state.seen)) {
      if (now - seenAt > SEEN_TTL_MS) delete this.state.seen[id];
    }
    for (const [number, chat] of Object.entries(this.state.chats)) {
      if (now - chat.lastSeen > CHAT_TTL_MS) delete this.state.chats[number];
    }
  }

  /** Coalesces bursts of writes; each flush is atomic via write-then-rename. */
  private scheduleWrite(): void {
    if (this.writeTimer) return;
    this.writeTimer = setTimeout(() => {
      this.writeTimer = null;
      this.flush();
    }, 300);
    this.writeTimer.unref?.();
  }

  flush(): void {
    try {
      const temporary = `${this.statePath}.tmp`;
      fs.writeFileSync(temporary, JSON.stringify(this.state));
      fs.renameSync(temporary, this.statePath);
    } catch (error) {
      log.error("Could not persist state", { error: (error as Error).message });
    }
  }

  /**
   * Records a message id and reports whether it is new. Meta re-delivers a
   * webhook until it gets a 200, so without this a slow reply becomes two.
   */
  markSeen(messageId: string): boolean {
    if (this.state.seen[messageId]) return false;
    this.state.seen[messageId] = Date.now();
    this.scheduleWrite();
    return true;
  }

  getChat(number: string): ChatState {
    const existing = this.state.chats[number];
    if (existing) return existing;
    const fresh: ChatState = { history: [], replyTimes: [], lead: {}, lastSeen: Date.now() };
    this.state.chats[number] = fresh;
    return fresh;
  }

  updateChat(number: string, mutate: (chat: ChatState) => void): ChatState {
    const chat = this.getChat(number);
    mutate(chat);
    chat.lastSeen = Date.now();
    this.scheduleWrite();
    return chat;
  }

  appendHistory(number: string, role: "user" | "assistant", content: string): void {
    this.updateChat(number, (chat) => {
      chat.history.push({ role, content });
      const maxEntries = env.historyTurns * 2;
      if (chat.history.length > maxEntries) {
        chat.history.splice(0, chat.history.length - maxEntries);
      }
    });
  }

  isHandedOff(number: string, now = Date.now()): boolean {
    const until = this.getChat(number).handoffUntil;
    return until !== undefined && until > now;
  }

  startHandoff(number: string, hours = env.handoffHours, now = Date.now()): void {
    this.updateChat(number, (chat) => {
      chat.handoffUntil = now + hours * HOUR_MS;
    });
  }

  clearHandoff(number: string): void {
    this.updateChat(number, (chat) => {
      delete chat.handoffUntil;
    });
  }

  /** Drops replies older than an hour and reports whether another is allowed. */
  canReply(number: string, now = Date.now()): boolean {
    const chat = this.getChat(number);
    chat.replyTimes = chat.replyTimes.filter((time) => now - time < HOUR_MS);
    return chat.replyTimes.length < env.maxRepliesPerHour;
  }

  recordReply(number: string, now = Date.now()): void {
    this.updateChat(number, (chat) => {
      chat.replyTimes.push(now);
    });
  }

  mergeLead(number: string, update: LeadUpdate): LeadUpdate {
    const chat = this.updateChat(number, (current) => {
      for (const [key, value] of Object.entries(update)) {
        if (value !== undefined && value !== null && value !== "" && value !== "unknown") {
          (current.lead as Record<string, unknown>)[key] = value;
        }
      }
    });
    return chat.lead;
  }

  /** Appends one line per qualified lead — easy to import into a spreadsheet. */
  recordLead(number: string, lead: LeadUpdate, profileName?: string): void {
    try {
      const row = JSON.stringify({ at: new Date().toISOString(), number, profileName, ...lead });
      fs.appendFileSync(this.leadsPath, `${row}\n`);
    } catch (error) {
      log.error("Could not append lead", { error: (error as Error).message });
    }
  }
}
