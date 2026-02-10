from typing import Optional
import math
from .mapping import map_properties
from .page_template import build_page_content


FORWARD_STAGES = [
    "applied",
    "received",
    "interview_scheduled",
    "interviewed",
    "final_round",
    "offer",
]
TERMINAL = {"rejected", "withdrawn"}


def choose_thread_key(row) -> Optional[str]:
    for key in ("conversation_id", "message_id"):
        val = row.get(key)
        if val is not None and not (isinstance(val, float) and math.isnan(val)) and str(val) != "":
            return val
    return None


def _norm_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text.lower() or None


def _extract_text(prop: Optional[dict]) -> Optional[str]:
    if not prop or not isinstance(prop, dict):
        return None
    if prop.get("type") == "title":
        items = prop.get("title") or []
    else:
        items = prop.get("rich_text") or []
    parts = []
    for item in items:
        text = item.get("plain_text") or item.get("text", {}).get("content")
        if text:
            parts.append(text)
    joined = "".join(parts).strip()
    return joined or None


def _get_prop_text(properties: dict, name: str) -> Optional[str]:
    return _extract_text(properties.get(name))


def _norm_stage(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        value = str(value)
    return str(value).strip().lower() or None


def allowed_stage_update(current: Optional[str], candidate: Optional[str]) -> bool:
    current = _norm_stage(current)
    candidate = _norm_stage(candidate)
    if not candidate:
        return True
    if current in TERMINAL:
        return False
    if current not in FORWARD_STAGES or candidate not in FORWARD_STAGES:
        return True
    return FORWARD_STAGES.index(candidate) >= FORWARD_STAGES.index(current)


def sync_row(row, client, database_id: str, merge_by_company_subject: bool = True):
    thread_key = choose_thread_key(row)
    if not thread_key:
        return "ERROR", None, "missing thread key"

    props = map_properties(row)
    props["Action Confirm"] = False
    content = build_page_content(row)

    found = client.query_by_conversation_id(thread_key)
    row_message_id = _norm_text(row.get("message_id"))
    if len(found) == 0:
        # Optional secondary match by company+subject when no thread hit.
        if merge_by_company_subject:
            company = _norm_text(row.get("company"))
            subject = _norm_text(row.get("subject"))
            if company and subject:
                secondary = client.query_by_company_subject(company, subject)
                if len(secondary) == 1:
                    page_id = secondary[0]["id"]
                    existing_msg_id = _norm_text(
                        _get_prop_text(secondary[0].get("properties", {}), "Message ID")
                    )
                    if row_message_id and row_message_id == existing_msg_id:
                        return "DONE", page_id, None
                    current_stage = secondary[0].get("properties", {}).get("Stage")
                    if not allowed_stage_update(current_stage, props.get("Stage")):
                        props.pop("Stage", None)
                    props["Status Updated"] = True
                    append_content = content
                    try:
                        page_text = client.get_page_plaintext(page_id)
                        body_text = (row.get("body") or "").strip()
                        if body_text and body_text in (page_text or ""):
                            append_content = None
                    except Exception:
                        append_content = content
                    client.update_page(page_id, props, content_append=append_content)
                    return "DONE", page_id, None

        page_id = client.create_page(props, content)
        return "DONE", page_id, None

    if len(found) == 1:
        page_id = found[0]["id"]
        existing_msg_id = _norm_text(_get_prop_text(found[0].get("properties", {}), "Message ID"))
        if row_message_id and row_message_id == existing_msg_id:
            return "DONE", page_id, None
        current_stage = found[0].get("properties", {}).get("Stage")
        if not allowed_stage_update(current_stage, props.get("Stage")):
            props.pop("Stage", None)
        props["Status Updated"] = True
        append_content = content
        try:
            page_text = client.get_page_plaintext(page_id)
            body_text = (row.get("body") or "").strip()
            if body_text and body_text in (page_text or ""):
                append_content = None
        except Exception:
            append_content = content
        client.update_page(page_id, props, content_append=append_content)
        return "DONE", page_id, None

    # Multiple matches: create a fresh page to avoid merging unrelated threads.
    page_id = client.create_page(props, content)
    return "DONE", page_id, None
