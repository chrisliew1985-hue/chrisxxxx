import { describeBusinessHours } from "./hours.js";
import { log } from "./logger.js";
import type { BusinessConfig, Rule } from "./types.js";

/** Lowercases and turns punctuation into spaces so keywords match cleanly. */
export function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** True when the keyword is plain ASCII/Latin, so `\b` boundaries are meaningful. */
function usesWordBoundaries(keyword: string): boolean {
  return /^[a-z0-9 ]+$/.test(keyword);
}

function keywordMatches(normalisedText: string, keyword: string): boolean {
  const needle = normalise(keyword);
  if (!needle) return false;
  if (usesWordBoundaries(needle)) {
    // `\b` keeps "hi" from matching inside "this".
    return new RegExp(`\\b${escapeRegex(needle)}\\b`).test(normalisedText);
  }
  // CJK and other scripts have no word boundaries; substring is the right test.
  return normalisedText.replace(/\s+/g, "").includes(needle.replace(/\s+/g, ""));
}

export interface RuleMatch {
  rule: Rule;
  score: number;
  matched: string[];
}

/**
 * Picks the best-scoring rule for `text`, or null when nothing matches.
 * Longer keyword hits beat shorter ones, so "book a viewing" wins over "hi".
 */
export function matchRule(text: string, rules: Rule[]): RuleMatch | null {
  const haystack = normalise(text);
  if (!haystack) return null;

  let best: RuleMatch | null = null;
  for (const rule of rules) {
    const matched = rule.keywords.filter((keyword) => keywordMatches(haystack, keyword));
    let score = matched.reduce((total, keyword) => total + normalise(keyword).length, 0);

    if (rule.regex && new RegExp(rule.regex, "iu").test(text)) {
      score += 10;
      matched.push(`/${rule.regex}/`);
    }
    if (score === 0) continue;

    score += (rule.priority ?? 0) * 5;
    // Strictly greater keeps the earliest rule in the file on a tie.
    if (!best || score > best.score) {
      best = { rule, score, matched };
    }
  }
  return best;
}

/** Values available to `{{placeholder}}` tokens in rule replies. */
export function templateValues(
  config: BusinessConfig,
  extra: Record<string, string | undefined> = {},
): Record<string, string> {
  const values: Record<string, string> = {
    agentName: config.agentName,
    agency: config.agency,
    hours: describeBusinessHours(config),
    areas: config.serviceAreas.join(", "),
    languages: config.languages.join(", "),
    signOff: config.signOff,
  };
  for (const [key, value] of Object.entries(extra)) {
    if (value) values[key] = value;
  }
  return values;
}

/** Substitutes `{{key}}` tokens; unknown tokens are dropped rather than shown. */
export function render(template: string, values: Record<string, string>): string {
  return template
    .replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, key: string) => {
      if (key in values) return values[key] as string;
      log.warn("Unknown template placeholder in reply, dropping it", { key });
      return "";
    })
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}
