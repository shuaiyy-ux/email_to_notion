from typing import Any
import html
import re


def _clean_body_for_notion(text: str, max_chars: int = 8000) -> str:
    if not text:
        return ""

    body = html.unescape(str(text))
    body = re.sub(r"<(br|p)[^>]*>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body)
    body = body.replace(" \n", "\n").replace("\n ", "\n")
    body = body.strip()

    if len(body) > max_chars:
        body = body[:max_chars] + " ...[truncated]"

    return body


def build_page_content(row: Any) -> str:
    sender = row.get("from", "") or ""
    subject = row.get("subject", "") or ""
    body = _clean_body_for_notion(row.get("body", "") or "")

    lines = [
        f"From: {sender}",
        f"Subject: {subject}",
        "",
        body,
    ]
    return "\n".join(lines)
