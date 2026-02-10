import pandas as pd
from pathlib import Path

from LLM import clean_email_body_for_llm


def summarize_bodies(xlsx_path: Path, top_n: int = 3, max_chars: int = 6000):
    df = pd.read_excel(xlsx_path, dtype=object)
    if "body" not in df.columns:
        raise ValueError("No 'body' column in the Excel file")

    lengths_raw = df["body"].fillna("").astype(str).str.len()
    cleaned = df["body"].fillna("").apply(lambda x: clean_email_body_for_llm(x, max_chars=max_chars))
    lengths_clean = cleaned.astype(str).str.len()

    print(f"Rows: {len(df)}")
    print(f"Max raw length: {lengths_raw.max()} chars")
    print(f"Max cleaned length: {lengths_clean.max()} chars")
    print(f"Raw >2000 chars: {(lengths_raw > 2000).sum()}")
    print(f"Cleaned >2000 chars: {(lengths_clean > 2000).sum()}")

    # Show top N longest raw bodies with their cleaned lengths.
    longest_idx = lengths_raw.nlargest(top_n).index
    for idx in longest_idx:
        print("-" * 40)
        print(f"Row {idx}: raw={lengths_raw[idx]} cleaned={lengths_clean[idx]}")
        snippet = cleaned[idx].replace("\n", " ")
        print(f"Cleaned snippet: {snippet}")


if __name__ == "__main__":
    xlsx_path = Path("Jobs.xlsx")
    summarize_bodies(xlsx_path)
