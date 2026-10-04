# Data quality report

Snapshot: 2026-09-28. Full-file scans of the priority tables.

| Source | Check | Affected records |
| --- | --- | ---: |
| cards | accepted_quality | 607,266 |
| cards | duplicate_current_rows_removed | 0 |
| cards | input_rows | 660,000 |
| cards | invalid_money_or_dpd | 52,734 |
| cards | served_accounts | 270,770 |
| case_account_links | accepted | 206,812 |
| case_account_links | customer_mismatch | 432 |
| case_account_links | missing_or_quarantined_account | 142,026 |
| cases | accepted | 338,295 |
| cases | duplicate_rows_removed | 0 |
| cases | input_rows | 367,229 |
| cases | invalid_account_list | 17,778 |
| cases | unresolved_customer | 11,156 |
| contacts | accepted | 2,425,462 |
| contacts | account_customer_mismatch | 2,430 |
| contacts | customer_reference_mismatch | 24,405 |
| contacts | duplicate_rows_removed | 0 |
| contacts | input_rows | 2,688,337 |
| contacts | unresolved_case | 236,040 |
| core_banking | accepted_quality | 780,000 |
| core_banking | duplicate_current_rows_removed | 0 |
| core_banking | input_rows | 780,000 |
| core_banking | served_accounts | 523,832 |
| customers | accepted_duplicate_pointers | 4,758 |
| customers | conflicting_key_rows | 0 |
| customers | input_rows | 1,020,000 |
| customers | missing_key_rows | 0 |
| customers | missing_or_invalid_dob | 5,026 |
| customers | missing_or_masked_phone | 14,459 |
| customers | quarantined_keys | 3,298 |
| customers | repeated_key_rows | 0 |
| lending | accepted_quality | 372,321 |
| lending | duplicate_current_rows_removed | 0 |
| lending | input_rows | 404,500 |
| lending | invalid_money_or_dpd | 32,179 |
| lending | served_accounts | 347,469 |
| notes | accepted | 678,595 |
| notes | account_customer_mismatch | 595 |
| notes | duplicate_rows_removed | 0 |
| notes | input_rows | 760,594 |
| notes | missing_text | 21,757 |
| notes | unresolved_case | 59,647 |
| promises | accepted | 219,789 |
| promises | account_customer_mismatch | 215 |
| promises | duplicate_rows_removed | 0 |
| promises | input_rows | 238,815 |
| promises | unresolved_case | 18,811 |

## Identity coverage

| Source | State | Source keys |
| --- | --- | ---: |
| cards | accepted | 228,590 |
| cards | quarantined | 321,410 |
| collections | accepted | 277,435 |
| collections | quarantined | 10,991 |
| core_banking | accepted | 437,269 |
| core_banking | quarantined | 206,933 |
| crm | accepted | 1,016,702 |
| crm | quarantined | 3,298 |
| lending | accepted | 316,003 |
| lending | quarantined | 23,997 |

Golden customer rows: 1,011,944.

Confidence categories describe matching evidence, not calibrated probabilities. Keys without sufficient complete identity evidence, inconsistent profiles, multiple candidates and unvalidated CRM duplicate pointers are quarantined.

Duplicate source rows are removed before joins. Conflicting payloads for a current entity key are quarantined, never chosen arbitrarily. Invalid money, DPD and required dates are quarantined.

Contacts reconcile channel/channel_v2; disagreements remain quarantined. Unlinked cases and interactions are retained in restricted tables for review.

The approved C360 excludes names, DOB, phones and protected attributes. Deposit balances are separate from credit/loan debt. Unknown totals remain null and have coverage counts.

This is a current snapshot foundation, not a historical feature store. This report audits foundation integrity only. The application separately implements feature parity, scoped access, question answering and local model workflows; their evaluation appears in the corresponding reports. CSV tables outside the priority set and Parquet histories have raw views but have not undergone row-level quality checks.

## Verification

- All five source systems have accepted identity links
- All three product sources have served account records
- Golden customer keys are unique
- Source identity keys are unique
- Every accepted link resolves to a golden customer
- Quarantined identity links have no golden ID
- Account keys are unique
- Case keys are unique
- All served case/account links agree on customer identity
- Served interactions have no contradictory resolved account owner
- Served transcripts agree with case and resolved contact provenance
- C360 credit/loan totals match separately aggregated accounts
- C360 matches its contract and excludes matching-only/protected fields
