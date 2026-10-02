"""Use Claude to read one WhatsApp chat and pull out CRM facts + appointments."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel, Field

from .whatsapp import Chat

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"


class Appointment(BaseModel):
    status: Literal["confirmed", "tentative", "cancelled"] = Field(
        description="confirmed = both sides clearly agreed on a date AND time. "
        "tentative = proposed/pending/'maybe'. cancelled = an earlier appointment was called off."
    )
    title: str = Field(description="Short calendar title, e.g. 'Viewing - Tropicana condo w/ Mr Tan'")
    start: str = Field(description="Local start time, ISO 8601 without offset: YYYY-MM-DDTHH:MM")
    duration_minutes: int = Field(description="Best estimate; use 60 if not stated")
    location: Optional[str] = None
    notes: Optional[str] = Field(None, description="Unit, price, who is coming, anything useful")
    replaces_start: Optional[str] = Field(
        None,
        description="If this reschedules or cancels an appointment listed under KNOWN "
        "APPOINTMENTS, that appointment's start (YYYY-MM-DDTHH:MM). Otherwise null.",
    )


class ChatAnalysis(BaseModel):
    contact_type: Literal["client", "owner", "agent", "personal", "other"] = Field(
        description="client = buyer, tenant or investor looking for a property. "
        "owner = property owner who wants to sell or rent out (seller / landlord). "
        "agent = another real-estate agent / negotiator / co-broke / agency staff. "
        "personal = friends/family. other = vendors, spam, service providers."
    )
    role: Optional[Literal["buyer", "tenant", "investor", "seller", "landlord", "unknown"]] = Field(
        None, description="For clients: buyer / tenant / investor. For owners: seller / landlord. "
        "Null for agents and others."
    )
    properties: Optional[str] = Field(
        None, description="Properties involved: for owners, the unit(s) they list (project, "
        "unit no., size, asking price/rent); for clients, units they viewed or are keen on."
    )
    potential: Literal["hot", "warm", "cold", "none"] = Field(
        description="hot = ready to act within ~2 weeks (viewing set, offer, budget + timing clear). "
        "warm = genuine interest but not urgent or still deciding. "
        "cold = slow / vague / unresponsive. none = personal/other."
    )
    potential_reason: str = Field(description="One sentence explaining the rating")
    summary: str = Field(description="2-3 sentence summary of the relationship and latest status")
    requirements: Optional[str] = Field(
        None, description="Budget, area, property type, size, move-in date, etc. if mentioned"
    )
    next_step: Optional[str] = Field(None, description="What the user should do next")
    appointments: list[Appointment] = Field(
        default_factory=list,
        description="Every appointment discussed in the NEW messages (viewings, meetings, "
        "calls, signing, handover). Include tentative and cancelled ones too.",
    )


SYSTEM_PROMPT = """You help a real-estate agent keep their CRM and calendar up to date from \
WhatsApp chats. Messages may be in English, Malay, Chinese or a mix; read them all.

You will be given one chat. "Me" is the agent who owns this WhatsApp. Messages before \
the NEW MESSAGES marker are older context; only report appointments that were \
arranged, changed or cancelled in the NEW messages.

Rules for appointments:
- Only mark "confirmed" when there is clear agreement on a specific date and time \
(e.g. "ok see you Sat 3pm", "confirmed", a thumbs-up to a specific slot). A proposal \
without acceptance is "tentative".
- Resolve relative dates ("tomorrow", "this Saturday", "明天", "esok") against the \
timestamp of the message that mentioned them.
- If an appointment from KNOWN APPOINTMENTS was moved, return it with the new time and \
set replaces_start to the old start. If it was called off, return status "cancelled" \
with replaces_start set.

Classify the contact from the whole conversation. Group chats with several agents are \
"agent"."""


def _format_chat(chat: Chat, new_since: datetime, tz: ZoneInfo, known: list[dict]) -> str:
    lines = [
        f"WhatsApp account: {chat.account}",
        f"Chat with: {chat.name}" + (f" ({chat.phone})" if chat.phone else ""),
        f"Group chat: {'yes' if chat.is_group else 'no'}",
        f"Timezone: {tz.key}",
        "",
        "KNOWN APPOINTMENTS (already in the calendar):",
    ]
    lines += [f"- {a['start']} {a['title']}" for a in known] or ["- none"]
    lines.append("")
    marked = False
    for m in chat.messages:
        if not marked and m.timestamp > new_since:
            lines.append("===== NEW MESSAGES =====")
            marked = True
        ts = m.timestamp.astimezone(tz).strftime("%Y-%m-%d %a %H:%M")
        lines.append(f"[{ts}] {m.sender}: {m.text}")
    return "\n".join(lines)


class Extractor:
    def __init__(self, timezone: str, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.tz = ZoneInfo(timezone)
        self.model = model

    def analyze(self, chat: Chat, new_since: datetime, known: list[dict]) -> ChatAnalysis | None:
        transcript = _format_chat(chat, new_since, self.tz, known)
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            # Server-side fallback: if a safety classifier declines, the API
            # retries the request on a fallback model inside the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript}],
            output_format=ChatAnalysis,
        )
        if response.stop_reason == "refusal":
            log.warning("Claude declined to analyse chat %s (%s); skipping", chat.name, chat.jid)
            return None
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            log.warning("Incomplete analysis for chat %s; skipping", chat.name)
            return None
        return response.parsed_output
