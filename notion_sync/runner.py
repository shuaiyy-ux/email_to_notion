from typing import Optional, List, Tuple
from .excel_io import read_excel, write_back_excel, iter_rows_for_sync
from .idempotency import sync_row
from .notion_client import HttpNotionClient, NotionClient, PROPERTY_TYPES
from .config import NOTION_TOKEN, NOTION_DATABASE_ID
from .mapping import PROPERTY_MAP


def sync_excel_rows(excel_path: str, client: Optional[NotionClient] = None, database_id: Optional[str] = None, out_path: Optional[str] = None, query_property: str = "Conversation ID", query_properties: Optional[list] = None, debug: bool = False, stop_on_error: bool = True, merge_by_company_subject: bool = True):
    client = client or HttpNotionClient(
        token=NOTION_TOKEN,
        database_id=database_id or NOTION_DATABASE_ID,
        query_properties=query_properties or [query_property, "Identity", "Name", "Message ID"],
        debug=debug,
    )
    db_id = database_id or NOTION_DATABASE_ID

    required_types = {k: PROPERTY_TYPES.get(k, "rich_text") for k in PROPERTY_TYPES.keys()}
    client.ensure_properties(required_types)

    df = read_excel(excel_path)
    errors: List[Tuple[int, str]] = []

    for idx, row in iter_rows_for_sync(df):
        try:
            status, page_id, error = sync_row(row, client, db_id, merge_by_company_subject=merge_by_company_subject)
        except Exception as e:
            import traceback
            print(f"Row {idx} error: {e}")
            traceback.print_exc()
            status, page_id, error = "ERROR", None, str(e)

        if page_id:
            df.at[idx, "notion_page_id"] = page_id
        df.at[idx, "llm_status"] = status
        df.at[idx, "error_msg"] = error

        if status == "ERROR" and stop_on_error:
            errors.append((idx, error or "unknown error"))
            break

    write_back_excel(df, out_path or excel_path)

    if stop_on_error and errors:
        first_idx, first_err = errors[0]
        raise RuntimeError(f"Notion sync stopped on row {first_idx}: {first_err}")

    return df
