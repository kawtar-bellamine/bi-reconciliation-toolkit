"""Escalation notes: one short Markdown file per issue, with the evidence the owner needs to act.

A note says what was seen, how big it is, which KPIs it touches, a few source lines as evidence, how to
reproduce it, the likely cause (a hypothesis) and the proposed action. It is written so that the person receiving
it does not need to come back with questions before starting.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .bronze import RAW_SHA256


def _cell(v) -> str:
    if v is None or (not isinstance(v, (list, tuple)) and pd.isna(v)):
        return ""
    if isinstance(v, pd.Timestamp):
        return f"{v:%Y-%m-%d %H:%M}" if (v.hour or v.minute) else f"{v:%Y-%m-%d}"
    return str(v).replace("|", "/")


def to_markdown(df: pd.DataFrame) -> str:
    df = df.copy()
    for c in [c for c in df.columns if c.endswith("_milli")]:
        df[c[:-6] + "_gbp"] = df.pop(c) / 1000
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    rows = ["| " + " | ".join(_cell(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def _sentence(text: str) -> str:
    text = str(text).strip()
    text = text[:1].upper() + text[1:]
    return text if text.endswith(".") else text + "."


def note(issue: dict, check: dict, sample: pd.DataFrame | None, window: str) -> str:
    value = issue.get("value_gbp")
    share = issue.get("share_of_gross_sales")
    lines = issue.get("lines")
    size = []
    if lines is not None and not pd.isna(lines):
        size.append(f"{int(lines):,} lines")
    if value is not None and not pd.isna(value):
        size.append(f"{value:,.2f} GBP" + (f" ({share:.2%} of gross product sales)" if share else ""))
    out = [
        f"# {issue['issue_id']}: {issue['title']}",
        "",
        "| | |",
        "|---|---|",
        f"| Severity | {issue['severity']} |",
        f"| Status | {issue['status']} |",
        f"| Proposed owner | {issue['owner']} |",
        f"| Size | {', '.join(size) if size else 'see evidence'} |",
        f"| KPIs affected | {issue['kpis_affected']} |",
        f"| Data | {window} |",
        "",
        "## What was seen",
        "",
        _sentence(check["observed"]) + (" " + _sentence(check["detail"]) if check.get("detail") else ""),
        "",
        "## Evidence",
        "",
        to_markdown(sample) if sample is not None and len(sample) else "No sample lines for this check.",
        "",
        "## How to reproduce",
        "",
        "```python",
        "from bitk.pipeline import run",
        "r = run()",
        f"r['checks'].query(\"check_id == '{issue['check_id']}'\")",
        "```",
        "",
        "## Likely cause (to confirm)",
        "",
        _sentence(issue["likely_cause"]),
        "",
        "## Proposed action",
        "",
        _sentence(issue["action"]),
        "",
    ]
    return "\n".join(out)


def write_notes(issues: pd.DataFrame, checks: pd.DataFrame, samples: dict, out_dir: str | Path,
                window: str) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chk = checks.set_index("check_id")
    paths = []
    order = {"high": 0, "medium": 1, "low": 2}
    for issue in sorted(issues.to_dict("records"), key=lambda i: (order[i["severity"]], i["issue_id"])):
        p = out_dir / f"{issue['issue_id']}.md"
        p.write_text(note(issue, chk.loc[issue["check_id"]].to_dict(), samples.get(issue["check_id"]), window))
        paths.append(p)
    index = ["# Escalation notes", "", f"Data: {window}", "",
             "| Issue | Severity | Title | Owner |", "|---|---|---|---|"]
    for p in paths:
        i = issues.set_index("issue_id").loc[p.stem]
        index.append(f"| [{p.stem}]({p.name}) | {i['severity']} | {i['title']} | {i['owner']} |")
    (out_dir / "README.md").write_text("\n".join(index) + "\n")
    return paths


def window_label(silver: pd.DataFrame) -> str:
    return (f"source extract {silver['date'].min():%Y-%m-%d} to {silver['date'].max():%Y-%m-%d}, "
            f"{len(silver):,} lines, file SHA-256 {RAW_SHA256[:12]}")
