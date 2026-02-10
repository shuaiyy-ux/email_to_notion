from __future__ import annotations
from pathlib import Path
import os
import sys
import re
import html
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ConfigDict

from openai import OpenAI

load_dotenv(Path(__file__).with_name(".env"))

if not os.getenv("OPENAI_API_KEY"):
    print("No APIKEY")
    sys.exit(1)

client = OpenAI()

Stage = Literal[
    "applied",
    "received",
    "interview_scheduled",
    "interviewed",
    "final_round",
    "offer",
    "rejected",
    "withdrawn",
    "needs_action",
    "forwarded",
    "other",
]

Priority = Literal["extremely high", "high", "medium", "low"]

NextAction = Literal[
    "reply",
    "schedule",
    "submit_materials",
    "complete_assessment",
    "sign_offer",
    "follow_up",
    "archive",
    "ignore",
    "escalate",
]

STAGE_DESCRIPTION = """
Choose exactly one stage label from the enum.

Definitions:
- applied: confirmation that an application was submitted or received by an ATS/system.
- received: acknowledgement or general update, no required action, interview not yet scheduled.
- interview_scheduled: interview time is scheduled or confirmed (including calendar invite confirmations).
- interviewed: interview already occurred (for example "thank you for interviewing", post interview follow-up).
- final_round: explicitly final round, panel interview, onsite final, last stage before offer.
- offer: explicit offer, offer letter, compensation details, or explicit steps to accept an offer.
- rejected: explicit rejection decision.
- withdrawn: candidate withdrew, or the company confirms withdrawal.
- needs_action: explicit action required from the candidate (reply, schedule/reschedule, submit materials/forms,
  complete an assessment, provide required information, confirm or sign offer). This label overrides non-termination stages.
- forwarded: the same job/process is handed off to a new contact person or new email (for example "handing you off",
  "new point of contact", "please contact X going forward"). This label describes contact transfer, not progress.
- other: cannot confidently map.

Decision order for stage:
1) rejected
2) withdrawn
3) needs_action
4) forwarded
5) offer, final_round, interviewed, interview_scheduled, received, applied
6) other

Constraints:
- Do not infer stage using any primary key or thread identifier. Only use email content and metadata provided.
- Do not invent events, times, deadlines, or facts that are not explicitly stated in the email.
""".strip()

PRIORITY_DESCRIPTION = """
Choose exactly one priority label from the enum.

Definitions:
- extremely high: explicit deadline within 24 hours, or explicit "ASAP", "immediately", "today", "by end of day".
- high: important action related to interview or offer, but no explicit within-24h deadline.
- medium: action required but not urgent.
- low: no action required, termination states, clearly irrelevant.

Constraints:
- If stage = needs_action, priority must be one of: extremely high, high, medium.
""".strip()

NEXT_ACTION_DESCRIPTION = """
Choose exactly one next_action label from the enum.

Definitions:
- reply: candidate should reply to confirm, answer questions, acknowledge receipt, or provide requested info.
- schedule: candidate should schedule or reschedule an interview or call.
- submit_materials: candidate should submit documents, forms, portfolio, transcripts, references, or similar.
- complete_assessment: candidate should complete a coding test, take-home, questionnaire, or assessment.
- sign_offer: candidate should review and sign an offer, or confirm acceptance.
- follow_up: candidate should follow up when there is no explicit request but a follow-up is appropriate.
- archive: no further action needed, record and close (typical for rejected or completed threads).
- ignore: spam, irrelevant, or no value.
- escalate: requires special handling outside normal workflow.

Constraints:
- If stage in {rejected, withdrawn}, next_action should usually be archive unless an explicit reply is requested.
""".strip()

SUMMARY_DESCRIPTION = """
A concise, action-oriented summary derived only from the email.
Include: the ask (if any), who to respond to, and any explicit deadline.
Do not invent facts, dates, or meeting times not present in the email.
""".strip()

class LLMResult(BaseModel):
    """
    Structured output contract for job-application email triage.

    Hard constraints:
    - Output must contain only these fields: stage, priority, next_action, importance_score, summary, company.
    - Do not add new fields or properties.
    - Do not use any primary key strategy or thread identifier guessing.
    - Use only the provided email metadata and body text.
    """
    model_config = ConfigDict(
        title="JobApplicationEmailTriage",
        json_schema_extra={
            "description": (
                "Return JSON matching this schema exactly. "
                "Do not add extra properties. Use only provided email content."
            )
        },
    )

    stage: Stage = Field(description=STAGE_DESCRIPTION)
    priority: Priority = Field(description=PRIORITY_DESCRIPTION)
    next_action: NextAction = Field(description=NEXT_ACTION_DESCRIPTION)
    importance_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "A number in [0, 1] indicating importance. "
            "Higher means more important. "
            "Base this on explicit urgency, interview or offer relevance, and required actions in the email. "
            "Do not infer hidden deadlines."
        ),
    )
    summary: str = Field(description=SUMMARY_DESCRIPTION)
    company: str = Field(
        description=(
            "Employer name inferred from sender domain, signature, subject, or body. "
            "If a reliable company name is already provided, keep it. If unsure, return empty string."
        )
    )

def sanitize_body_text(text: str) -> str:
    if not text:
        return text

    text = text.replace("_x000D_", "")

    text = text.replace("_x000A_", "\n")

    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    
    return text.strip()


def clean_email_body_for_llm(text: str, max_chars: int = 6000) -> str:
    """Strip HTML to plain text, normalize whitespace, and keep length bounded for the model."""
    if not text:
        return ""

    body = html.unescape(str(text))

    # Convert common HTML breaks to newlines before dropping tags.
    body = re.sub(r"<(br|p)[^>]*>", "\n", body, flags=re.IGNORECASE)

    # Remove remaining tags.
    body = re.sub(r"<[^>]+>", " ", body)

    # Collapse whitespace and normalize newlines.
    body = re.sub(r"\s+", " ", body)
    body = body.replace(" \n", "\n").replace("\n ", "\n")

    body = body.strip()

    if len(body) > max_chars:
        body = body[:max_chars] + " ...[truncated]"

    return body

def build_prompt(from_: str, subject: str, company: str, received_utc: str, body: str) -> str:
    body = sanitize_body_text(clean_email_body_for_llm(body))
    return f"""
You are an email triage classifier for job applications.

Output must be a single JSON object that matches the provided JSON schema exactly:
- Use only the schema fields.
- Do not add any extra keys.
- Use only the email metadata and body below.
- Do not invent facts, deadlines, or times not present in the email.
- next_action must be one of: reply, schedule, submit_materials, complete_assessment, sign_offer, follow_up, archive, ignore, escalate.
- company: infer employer name from sender domain/signature/subject/body; if provided company looks reliable, keep it; if unsure, use empty string.

Email metadata:
from: {from_}
subject: {subject}
company_hint: {company}
received_utc: {received_utc}

Email body:
{body}
""".strip()

def call_llm_structured(prompt: str) -> dict:
    r = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        input=prompt,
        text_format=LLMResult,
    )
    obj: LLMResult = r.output_parsed
    return obj.model_dump()
