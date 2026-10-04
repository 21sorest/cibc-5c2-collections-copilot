# Dataset inspection and first implementation

The release README, schema.json, CSV headers, certified metric definitions, operational events, benchmark questions and example DC-COLL-001 were inspected before implementation.

The release has 31 tables, 1,020,000 CRM records representing approximately one million people, 25,000 transcript files, 35 benchmark questions, 15 metric definitions and six documented operational events. All records are synthetic. Full measured priority-table counts are in reports/data_quality.md after a successful build.

## Decisions from actual source conventions

- Preserve all CSV IDs as text, including the core banking 10-digit CIF. An empty field is null; the outcome code NA remains literal text.
- CRM uses crm_customer_id. Cards, lending and core banking each use src_customer_ref. Collections uses coll_customer_ref, copied from CRM. These keys must not be joined as if they shared one namespace.
- Canonical CRM date_of_birth is used for matching. Source numeric dates such as 07-02-1990 retain both possible interpretations. A unique candidate must also agree on full phone and name evidence. No calendar convention is guessed.
- Full names tolerate case, accents, separators and word ordering. Initial-only given names require a full surname, matching first/middle initials, DOB and a full phone, with a unique candidate. These matches receive medium confidence. Initials or names alone never establish identity.
- Validate duplicate_of_crm_id against an existing nonduplicate CRM record with matching normalized first/last name and DOB. Reject broken pointers, contradictory profiles and duplicate chains for review.
- Reconcile channel and channel_v2 from contact_history. The release event REL-0926 documents the rename. Contradictory nonempty values are quarantined.
- Distinguish deposit balances from credit/loan outstanding amounts. The release is primarily CAD; non-CAD deposit balances are not converted or counted as CAD.
- Do not use final payment outcomes to reconstruct historical features. This first build is a current snapshot, not a point-in-time training dataset.

## Benchmark implications

The benchmark requires more than individual case lookup. It includes aggregate SQL metrics, policy retrieval, transcript summaries, operational incidents, historical roll rates and refusal cases. The question interface must later use these same data definitions, not a separate manually filled answer sheet.

Relevant sources include contacts, promises, cases, card/loan accounts, account_monthly_snapshot, agents, channel_capacity, ops_events, policy documents and transcripts. Source views exist for all 31 tables; only the priority entity/interaction tables have curated row-level validation in this milestone.

Policy applicability matters. POL-COLL-004 v4.2 supersedes v4.1 for the current hardship policy. Retrieved notes and transcripts are evidence data and must not become executable instructions. Bulk PII exports, protected-attribute ranking and unrelated questions must be refused by the future question interface.

## Scope of this milestone

Implemented: raw source views, priority-table normalization and deduplication, identity mapping across five source systems, quarantine reasons, golden C360, case-account links, contacts, promises and note source metadata. Raw note text remains outside the approved C360.

Subsequent work implements a local review UI, scoped deterministic questions, applicable policy section retrieval, rules-based text signals, a versioned current feature store, an optional AI-summary adapter and a system-generated benchmark CSV. Later work added local authentication and assignment checks, trained text signals, pretrained local speech/generation, all six use-case prototypes, and an eight-slide pitch draft. Historical feature snapshots, paid API verification, independent semantic evaluation and video recording remain pending. See README.md and the measured reports for the current state.
