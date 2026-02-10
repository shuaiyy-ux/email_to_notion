import pandas as pd
from schema_converter import schema_converter
from datetime import datetime, timezone
from LLM import build_prompt, call_llm_structured
from notion_sync.runner import sync_excel_rows
from notion_sync.excel_io import write_back_excel
from local_copy_manager import copy_and_merge_to_local, get_local_copy_path

ONEDRIVE_XLSX = "/Users/cm/Library/CloudStorage/OneDrive-UCIrvine/Jobs.xlsx"
LOCAL_XLSX = get_local_copy_path(ONEDRIVE_XLSX)


def run_llm(path: str):
    df = pd.read_excel(path)
    df = schema_converter(df)
    status_col = df["llm_status"].fillna("").astype(str).str.strip().str.upper()
    mask = (status_col == "NEW") | (status_col == "")
    indices = df[mask].index.tolist()

    for i in indices:
        try:
            row = df.loc[i].fillna("")

            prompt = build_prompt(
                from_=row["from"],
                subject=row["subject"],
                company=row["company"],
                received_utc=row["received_utc"],
                body=row["body"],
            )

            llm_output = call_llm_structured(prompt)

            allowed_next_action = {
                "reply",
                "schedule",
                "submit_materials",
                "complete_assessment",
                "sign_offer",
                "follow_up",
                "archive",
                "ignore",
                "escalate",
            }
            if llm_output.get("next_action") not in allowed_next_action:
                raise ValueError(f"next_action invalid: {llm_output.get('next_action')}")

            for k, v in llm_output.items():
                df.at[i, k] = v

            df.at[i, "llm_status"] = "DONE"
            df.at[i, "llm_processed_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            df.at[i, "error_msg"] = ""
        except Exception as e:
            df.at[i, "llm_status"] = "ERROR"
            df.at[i, "llm_processed_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            df.at[i, "error_msg"] = str(e)

    write_back_excel(df, path)
    return df


def run_full(onedrive_path: str = ONEDRIVE_XLSX, force_refresh: bool = False):
    print("[STEP 1] Copy from OneDrive and merge...")
    local_path, stats = copy_and_merge_to_local(onedrive_path, force_refresh=force_refresh)
    added = stats.get("added", 0)
    kept = stats.get("kept", 0)
    pending = stats.get("pending", 0)
    print(f"[AUDIT] added={added}, kept={kept}, pending={pending}")

    if added == 0 and kept == 0 and pending == 0:
        print("[STOP] No changes detected. Abort.")
        return None

    if pending == 0:
        print("[STOP] Changes detected but no pending rows. LLM/Notion skipped.")
        return None

    print("[STEP 2] LLM start")
    df_llm = run_llm(local_path)
    print("[STEP 2] LLM done")

    print("[STEP 3] Notion sync start")
    try:
        df_sync = sync_excel_rows(local_path, debug=True, stop_on_error=True)
    except Exception as e:
        print(f"[STEP 3] Notion sync failed: {e}")
        return None
    print("[STEP 3] Notion sync done")

    print(f"[DONE] Local file: {local_path}")
    print(f"[INFO] To sync back to OneDrive, copy {local_path} -> {onedrive_path}")
    return df_sync


if __name__ == "__main__":
    run_full()
