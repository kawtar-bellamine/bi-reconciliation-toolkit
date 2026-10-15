# Support runbook: first response to a report problem

What to check first, what evidence to collect, and when to hand over, for the five kinds of tickets a reporting
support desk receives most. The aim is that a ticket escalated to the data, platform or source team arrives with
enough evidence to be worked on without a round of questions.

Every escalation note in [`results/escalations/`](../results/escalations/) follows the same layout: what was
seen, size, KPIs affected, sample lines, how to reproduce, likely cause, proposed action, proposed owner.

## 1. "The figures are wrong" or "they do not match another report"

1. Ask for the exact page, filters, period and the figure the user expected, with where it comes from.
2. Check the definitions first: are both figures the same KPI? Gross against net sales, or invoice date against
   cancellation date, explains many tickets. The KPI dictionary (`kpi/kpi_dictionary.csv`) is the reference.
3. Check the period: is the last month partial (check Q11)? Is the last day complete?
4. Reconcile at the same grain: `python -m bitk report_a.csv report_b.csv --keys month,country --measures ...`
   shows which months and countries differ.
5. Walk the bridge (`results/sales_bridge.csv`) to see which line types make the gap.
6. Escalate only what is left, with the cells that differ and sample lines.

## 2. Refresh failed

1. Read the error message and note the time, the dataset and the step that failed (source connection,
   Power Query step, or model load).
2. Check whether the source extract arrived, and whether its row count and totals look like a usual day
   (control totals, check R1).
3. Look for a schema change: a renamed or new column, a new code format (the "new product codes" fault), a
   changed date or number format (the "date format swap" and "decimal shift" faults).
4. If the data is the cause, escalate to the source owner with the failing column and sample values. If the
   source is fine, escalate to the platform team with the error message and the time.

## 3. A visual is broken or blank

1. Reproduce with the same filters and the same user rights.
2. Check for blank members: lines whose key has no match in a dimension (keys checks K) or an unknown
   customer (-1). A filter on a dimension silently drops those lines.
3. Check whether a measure divides by zero or by a blank (ratios use `DIVIDE`).

## 4. The report is slow

1. Note which page and which visual, and the time it takes.
2. Use the Performance analyzer in Power BI Desktop to see whether time goes to the DAX query or to the visual.
3. Usual causes: too many visuals on one page, high-cardinality columns in slicers, calculated columns that
   should be measures, a missing star schema (joins done in DAX).

## 5. Access problem

1. Note the user, the workspace or app, and what they see (no access, empty report, partial data).
2. An empty or partial report for one user usually means row-level security, not missing data: compare with a
   user who sees the data.
3. Escalate to the workspace administrator with the user, the item and the role they should have.
