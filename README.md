# Collections Copilot

Team 5C2's CIBC Collections Hackathon prototype for agent assist.

Repository: https://github.com/21sorest/cibc-5c2-collections-copilot

Required submission files: `docs/architecture.png`, `contracts/c360.json`, `reports/data_quality.md` and **`submission/benchmark_answers.csv`**. The CSV currently contains all 35 released questions in the organizer template format. The 15 extra questions due at 7 PM IST on 4 October 2026 must be added with `python questions.py --benchmark --extra PATH_TO_EXTRA_QUESTIONS.csv`; the runner writes that exact submission path.

## Status

The local prototype connects the data foundation, 12 versioned case features, supported SQL/policy questions, conversation assistance, decision proposals, post-call evidence and employee review in Streamlit. A locally trained classifier detects financial hardship. Local Qwen LoRA training and its narrow held-out factual-format evaluation have completed; all 1,803 approved recordings were transcribed using pretrained Whisper. Optional OpenAI drafting remains untested. No paid application API calls have been made.

The five additional workflows now include action reasons/alternatives and programme screens, channel uncertainty and operational prerequisites, multi-skill staff routing, timestamped structured summaries and per-item employee QA observations. See [the implementation and limitations](docs/deeper_use_cases.md). They remain reviewed hackathon workflows, not validated optimal treatments or automated compliance decisions.

Milestone 1 was verified against the full priority CSV tables: 1,011,944 golden customers, 1,142,071 served accounts and 338,295 served cases. The refreshed build took 245.2 seconds and passed all 13 integrity checks, including a second check after reopening the saved database. Case `CS-2026-614370` was inspected with its linked customer, account, contacts, promises and note references. Uncertain identity links remain quarantined; the report records incomplete account coverage.

The feature build covers all 338,295 served cases. A 100-case parity check compares the online reader with the persisted offline feature rows. All 12 public development SQL benchmark tables match their gold references within tolerance. Policy and transcript answers need semantic review; hidden-test correctness has not been claimed. The refreshed rules-based development baseline measures hardship precision/recall of 93.98%/93.98% across 435 approved public-labelled notes. The separate 101-call development hold-out measures 97.87% precision and 85.19% recall. Its examples were excluded from rule tuning, but original aggregate public-label metrics had already been inspected, so this is not a blind test. Source approval excludes unavailable or contradictory evidence; the evaluated count is not all 500 labels. Missing coverage and imperfect recall require employee review. Cease-request precision is low; signals trigger review rather than proving a legally effective request. See `reports/text_evaluation.json` for exact scope and support.

## Build objective

An agent selects a case, inspects a unified customer record and versioned features, asks a question with SQL or source evidence, and reviews a grounded case brief and proposed assistance step. Record accept, edit and reject decisions. Do not send messages or change payment arrangements automatically.

All four layers must connect end to end:

1. Raw-to-curated-to-golden C360 pipeline, cross-system ID matching with confidence and data quality checks.
2. Natural-language questions over approved data and policy, with SQL/sources and out-of-scope refusal.
3. Shared structured and text feature definitions, current snapshot, explicit historical limitations and an offline/live parity check.
4. Agent assist with explanations, policy checks and human review.

## Changes from the Phase 1 design

The Phase 1 Agent Assist goal remains the primary workflow. The build uses DuckDB and Streamlit for a reproducible local implementation, with SQLite for employee reviews; service/database deployment components are deferred. Current-only source facts support a dated feature snapshot rather than fabricated historical training rows. Cross-system source IDs are reconciled through validated identity evidence and quarantine, and approved C360 amounts keep deposits separate from debt.

The AI approach now includes a team-trained hardship classifier, pretrained local Whisper transcription and a locally fine-tuned Qwen adapter for a narrow factual task. Optional paid drafting remains untested. Model output selects cited exact fields; deterministic rules retain contact gates and employee control. All six assistance workflows are implemented, with explicit limitations instead of an automatic collections agent. The Phase 1 preparation-time improvement target remains unmeasured.

The architecture PNG is a programmatic engineering diagram rendered by `docs/render_architecture.py`, with auditable diagram source in `docs/architecture.mmd`. No image-generation model was used.

## Implemented stack

Python and DuckDB implement the data foundation and feature store; Streamlit provides the case workspace. Questions route to trusted parameterised SQL or applicable policy sections, with source evidence and refusals. User SQL is never executed. Free-form model-generated SQL and SQLGlot are deferred. FastAPI and PostgreSQL are deferred while one local DuckDB database supports the prototype. SQLite stores review decisions separately so the case database stays read-only during serving.

The optional OpenAI Responses adapter selects typed facts from approved structured evidence. Each fact contains a source, field and exact canonical value; the application verifies equality and renders sentences itself. Local Qwen uses a narrower case-only task and the same validator. Grounding and complete required-field coverage are distinct: a correct partial response can still omit important facts. Neither model can change contact gates or proposed steps. A word/bigram naive Bayes classifier is trained locally from public labeled text; its tokenizer is shared between training and inference. Rules remain stronger on rare signals. Public-label results are development evaluations, not organizer-held-out results.

## First steps

1. Download the main release from https://huggingface.co/datasets/nuxsh/maple-collections-hackathon into `maple_data/`. Reserve about 10 GB without optional voice files.
2. Read the release README before implementing joins or features. Inspect actual keys, benchmark templates, metric definitions, policies and label schemas.
3. Implement the C360 pipeline and count data quality failures across the five source systems. Quarantine ambiguous identity links.
4. Connect one dataset-backed case through the four layers before expanding coverage.
5. Add the remaining approved features, benchmark runner, evaluation and submission materials.

Do not commit API keys, dataset downloads, generated databases or voice files. Commit source code, contracts, evaluation summaries and required submission artifacts.

## Suggested 36-hour work allocation

These are relative work blocks, not a statement of time remaining. Deadline: 4 October 2026, 9:00 PM IST.

| Hours | Deliverable |
| --- | --- |
| 0-2 | Data download, release README, schema/benchmark inspection, API access check |
| 2-8 | Curated data, cross-system identity mapping, C360, quality counts, first customer view |
| 8-14 | Versioned structured features, text extraction, source evidence, snapshot parity |
| 14-21 | Scoped questions, validated read-only SQL, policy retrieval, automated benchmark export |
| 21-27 | Case brief, action eligibility gates, accept/edit/reject workflow and audit history |
| 27-32 | Full-data checks, label evaluation, latency/cost measurement, failure fixes |
| 32-36 | README, final diagram, contract, quality report, video, deck and final benchmark run |

Reserve 4 October, 7:00-9:00 PM IST for the extra benchmark questions, final run and submission. Complete most packaging beforehand.

## Evaluation

- Generate benchmark answers through the same question-answering path as the UI. Never hand-edit answers.
- Match the release template exactly: `question_id`, `answer`, `sql_or_sources`, `refused`.
- Check deduplication, identity ambiguity, join multiplication, missing dates, schema drift, feature freshness and point-in-time correctness.
- Evaluate text signals against compatible public labels. If label fields do not cover a signal, use a separately reviewed sample.
- Check source citations, unsupported claims, hardship recall, refusal behavior and consent/hold enforcement.
- Measure case preparation time against manual lookup. The design's 30% improvement is a target, not a result.

## Submission checklist

- Private GitHub repository with organisers added when their account details are announced; commits throughout the hackathon.
- README with verified run instructions, actual design changes and AI tool disclosures.
- Final architecture PDF or PNG in the repository.
- C360 YAML or JSON contract, based on release example `DC-COLL-001`.
- Data quality report with affected-record counts and handling.
- System-generated CSV for all released benchmark questions, including the extra set released at 7:00 PM IST on 4 October.
- Demo video of at most five minutes, showing the released dataset, submitted by link.
- Pitch deck of at most ten slides, exported as PDF and submitted separately.

Commits after 4 October, 9:00 PM IST are not considered.

## Running the data foundation

Use Python 3.12. From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest -v test_pipeline
.\.venv\Scripts\python.exe pipeline.py build
.\.venv\Scripts\python.exe pipeline.py case --case-id CS-2026-614370
.\.venv\Scripts\python.exe features.py build
.\.venv\Scripts\python.exe features.py evaluate
.\.venv\Scripts\python.exe -m unittest -v test_workflows
.\.venv\Scripts\python.exe questions.py --benchmark
.\.venv\Scripts\python.exe evaluate_benchmarks.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The release must exist at `maple_data/maple_collections_release`, or pass `--release PATH` to the build command. The default database is `data/collections.duckdb`; pass `--database PATH` to use another file. The default cutoff is the supplied snapshot date, 28 September 2026. An arbitrary historical `--as-of` date is not a supported training snapshot because the release contains current-only facts.

The build scans the full priority CSV tables and creates lazy raw views for the remaining tables, including Parquet histories. It does not load all histories into Python memory. A failed transaction preserves the preceding successful database build. Rebuilding replaces the current snapshot. The case command is a local inspection tool, not an authenticated application.

Outputs:

- `reports/data_quality.md`: measured quality counts, match coverage and passed checks.
- `reports/quality_summary.json`: machine-readable metrics and source schema inventory.
- `contracts/c360.json`: product owner, schema, quality rules, permitted uses and refresh.
- `docs/dataset_inspection.md`: source conventions, design changes and remaining scope.
- `contracts/features.json`: feature definitions, missingness, windows and known limits.
- `reports/features_summary.json`, `reports/text_evaluation.json`: measured feature coverage and text development metrics.
- `reports/benchmark_answers.csv`, `reports/benchmark_dev_evaluation.json`: system-generated answers and development numeric checks.
- `docs/architecture.png`, `docs/architecture.mmd`: implemented architecture, with optional and pending components identified.
- `docs/demo_script.md`: a recording plan under five minutes.

Open http://127.0.0.1:8501 for the local case workspace. The default example is CS-2026-614370. The snapshot-time checkbox enables an explicitly labelled demonstration; using the real current time blocks contact because the release is stale. Accepted, edited and rejected reviews are stored in `data/reviews.sqlite`, with reviewer, brief, decision time, versions and a hash chain. A review never executes contact or changes a payment arrangement. Without an account file the reviewer field is a clearly labelled demo identity.

Database schemas separate raw/restricted material from approved curated/golden tables, but are not access-control boundaries. The app binds to localhost. Optional local accounts enforce agent case assignments and supervisor-only aggregate analytics. Production deployment still needs an identity provider, TLS and deployment review. Identity confidence is categorical evidence, not a probability. Unmatched accounts do not contribute to C360 amounts, which carry explicit coverage counts. Financial and matching metadata remain in the local ignored database.

## Local accounts

Run `python access.py create --user YOUR_USERNAME --role supervisor` in your own terminal to create an account. The command asks for a password of at least 12 characters without echoing it. For an agent use `--role agent --agent-id AG-2407`, substituting the correct dataset employee ID. Credentials are salted PBKDF2 hashes in ignored `data/users.json`. The app requires login whenever that file exists. Agent case lookups and transcript questions are checked against assignment, and aggregate analytics requires supervisor access. Reviews use the signed-in username. Sessions expire after one hour, and failed logins trigger a session-level cooldown. This local account mechanism is a prototype; an internet-facing service needs a managed identity provider and stronger rate limiting.

## Optional AI summary

Copy `.env.example` to `.env` and set `OPENAI_API_KEY` and `OPENAI_MODEL` locally. Do not commit or paste the real key into the interface. Use a model available to your API account that supports Responses structured output. Restart Streamlit, then click **Draft AI summary from approved facts**. Each click can incur API charges; the normal screen and benchmark path make no paid calls. Source text and direct identifiers such as names, phone numbers, addresses and DOB are excluded from the AI request. Case/account IDs and approved financial facts are sent. Model-selected source/field/value triples must match the evidence exactly; the application renders the sentences. Exact grounding does not establish useful selection, completeness or source accuracy. Employee review remains required. Provider usage and latency are retained with the reviewed brief.

Implementation references: [Responses migration](https://developers.openai.com/api/docs/guides/migrate-to-responses) and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Remaining submission work

- Test paid AI drafting only after credentials and billing authorization. Assess required-field coverage and usefulness separately from exact grounding.
- Evaluate broader summary usefulness independently. The local LoRA training and frozen factual-format comparison are complete; their narrow results do not establish conversation quality.
- Extend policy/transcript semantic evaluation beyond the 24 source-grounded development acceptance checks. Extra benchmarks remain unverified; keep their answers separate from training.
- Configure and validate access accounts, then integrate production identity management and a maintained provincial holiday calendar before deployment. This release supports only the current snapshot, not historical training features.
- Measure case-preparation time against manual lookup, plus runtime AI latency and cost. No 30% improvement claim has been measured.
- The private repository is connected and the source is committed. The `cibchack26` organizer invitation was sent and is awaiting acceptance; push subsequent benchmark updates before the deadline.
- Review the prepared nine-slide pitch PDF, record the demo, and run the additional questions released on 4 October at 7 PM IST. Final deadline is 9 PM IST.

When the extra questions arrive, place the organizer CSV locally and run `python questions.py --benchmark --extra PATH_TO_EXTRA_QUESTIONS.csv`. It must contain `question_id` and `question_text`, with optional `as_of_date` matching the supplied snapshot. The runner merges unique questions and rejects conflicting IDs. It writes lowercase `true`/`false` refusal values. Unsupported new questions still need implementation and verification through the application path.

## AI tools used so far

Codex read the supplied documents, downloaded the synthetic main and optional voice releases, implemented and tested the pipeline, features, question catalogue, six employee-reviewed local use cases, review logging and generation adapters, and prepared contracts and submission drafts. Reviewing subagents audited source handling, safety and training integrity. The team-trained classifier is a local word/bigram model. Whisper and the baseline Qwen are pretrained. A completed LoRA experiment adapts pretrained Qwen to three cited factual fields. Its saved training and frozen final reports support the narrow result; it is not training from scratch. No paid application API calls have been made. Prompt versions are recorded in generation metadata. Public development reference SQL informed metric validation. Benchmark CSVs are generated through `questions.answer`, never manually filled.

## Overnight additions and local models

Run `python train_classifier.py train` after the foundation build. This requires only the base dependencies. The model is stored in ignored `data/models/text_classifier.json`, and `reports/classifier_evaluation.json` records its checksum, source coverage and grouped split. There are 678 training examples and 181 evaluation examples, grouped by customer, normalized/redacted text and complete token signature. Twenty-five examples labeled as containing protected content are excluded; 116 additional labels lack approved matching sources. Pure hardship precision and recall are both 98.61% on this development partition. The earlier split had overlapping token inputs and its score is superseded. Short live utterances may differ from full training notes/calls. Rare-class outputs are shown as review evidence and do not replace the rules.

Conversation assistance retrieves applicable policy, gates disclosure on employee-confirmed identity verification, proposes a response and follow-up questions, and drafts a signal-only note without copying protected personal details. Next Best Action follows hold/dispute/hardship/promise precedence. Channel comparison requires operational evidence, sufficient known outcomes and separated uncertainty before a ready preference. Sparse comparisons support investigation only. Agent routing checks language, required skills, French-site evidence, mandatory support certification and free snapshot capacity. Post-call review identifies customer signal timestamps and shows evidence for the ten QA items; it does not certify compliance or invent a payment promise. Every use case has employee review and executes no action.

For speech, install `requirements-audio.txt`, download the optional voice zip, then run `python speech.py prepare --limit 5` and `python speech.py evaluate --limit 5 --model base.en`. The archive and individual audio checksums are verified. Five-recording comparison: tiny.en WER 25.45%, base.en WER 16.11%. Expanded base.en evaluation on 20 recordings measured WER 17.07% in 107.7 seconds total CPU time. These are synthetic English TTS examples; punctuation/case are ignored and number-format differences affect WER. Mixed speakers require employee attribution before customer signal extraction. Matched recordings and generated transcripts appear in Post-call review, with playback. Sample-specific reports preserve evaluation scope.

For local generation, install `requirements-local-llm.txt` and download the official `Qwen/Qwen2.5-0.5B-Instruct-GGUF` file `qwen2.5-0.5b-instruct-q4_k_m.gguf` into `data/models/`. Its expected SHA256 is checked by `local_llm.py`. Run `python evaluate_local_llm.py`. The current typed-fact report records ten open-case outputs passing exact source/field/value checks, with median CPU latency 7.02 seconds. The model selects fields and the application renders sentences; free-form claims are not displayed. Grounded output does not establish complete or useful selection. The deterministic brief remains the default and fallback. Downloaded models stay local; inference does not require an account or paid API.

The local LoRA fine-tune completed on 1,529 synthetic factual-format examples in 721.25 seconds, updating 540,672 adapter parameters. Final evaluation passed 468/468 complete exact-value outputs across 117 customer-separated cases and four variants. Median GPU generation latency was 4.65 seconds, excluding model load. The unchanged baseline passed 0/468 with this wrapper; a stronger source-key prompt passed 7/10 separate development examples, versus 10/10 for the adapter. This demonstrates narrow format adaptation, not general financial reasoning. The optional adapter is enabled only while model, prompt, corpus and result hashes match; deterministic controls and fallback remain. See docs/local_llm_training.md.

Run `python export_c360.py` to prepare `data/c360_release/` for user-managed Hugging Face upload. It contains the 1,011,944-row compressed C360, checksum manifest, contract, quality report and dataset card. No upload occurs. Add the final dataset URL to the README after publication.

Submission drafts: `submission/5C2_pitch_draft_v9.pdf` and its editable PPTX. Review their content before final submission. Deck sources are `docs/build_deck.mjs` and `docs/export_deck_pdf.py`, using the bundled artifact runtime. The PDF uses high-resolution slide renders; the PPTX retains editable text and its numeric chart.

Local UI integration checks: `python -m unittest -q test_ui` needs the built dataset and verifies temporary login, assignment selection, reviewer identity, conversation assistance, supervisor-only aggregate queries and sign-out. CI skips that integration check when the dataset is unavailable.

Short-utterance stress checks identified false model flags for explicit denials and affordability statements. Conversation hardship now uses the shared `review_signals` helper: positive rules, or an uncalibrated model score of at least 0.95 without an explicit denial. The report separately measures the pure classifier and the live combination. Rules scan all mentions so an earlier denial cannot hide a later positive statement. These development safeguards do not prove short-utterance accuracy.

On the refreshed 181-example development partition, the live combination measures 94.74% hardship precision and 100% recall, compared with 98.61%/98.61% for the pure classifier. The live combination detects all 72 positive examples with four false positives. These flags are review cues, not confirmed hardship status. This trade-off prioritizes avoiding missed support needs while preserving employee verification.

`python evaluate_fairness.py` audits 181 development examples by protected-field slices without feeding those fields into scoring. Low-support slices are suppressed. Four protected-prefix probes each left all 181 hardship flags unchanged. This small synthetic audit is not a fairness certification. See `reports/classifier_fairness.json`.

Proposal safeguard audit: `python evaluate_decisions.py` checks up to five approved cases per status, policy state, hardship and recorded-vulnerability stratum. The development run checked 719 cases with no failures of the tested consent, hold, staff language/capacity and stale-data requirements. This is not a benchmark of optimal recommendations. See `reports/decision_safeguards.json`.

See `docs/model_decisions.md` for local model choices and rubric adaptation. The earlier paired 20-recording speech check measured 12.31% WER for small.en and 17.07% for base.en. After stricter transcript provenance approval, the refreshed 100-recording small.en check measured 11.22% WER in 966.4 seconds of CPU run time. Transcription of all 1,803 approved recordings completed with 11.02% aggregate WER in 13,699.9 seconds (3.81 hours) of CPU time. See reports/speech_evaluation_small_en_2000.json; the filename records the requested limit, while actual approved sample count is 1,803. The CLI defaults to small.en. These are synthetic English development samples ordered by voice ID, with employee speaker review required.

Local LoRA training and the implementation review pass are complete. Broader independent evaluation remains limited by the supplied synthetic data. Current test evidence belongs in the progress log rather than a stale fixed count here. The final rubric/extra questions, account connections, a human timing study if claiming savings, and video/final submission still need the user. Start with `docs/handoff.md`. No paid application API calls or dataset/model uploads occurred. Source code and submission artifacts are published to the private repository.

Latest verification: 136 automated checks passed with no failures or skips. The current proposal audit checks 719 approved cases; 24 source-grounded policy/scope acceptance checks complement 12 numeric public benchmarks. See reports/implementation_checks.json, reports/decision_safeguards.json, reports/question_semantics.json and docs/deeper_use_cases.md for scope and limits.

Extra organizer questions are included in `submission/benchmark_answers.csv`: all 50 question IDs, with 41 answers and 9 refusals. The 15 extras contain 12 answers and 3 privacy/protected-ranking refusals. Regenerate with `python questions.py --benchmark --extra benchmark_questions_extra.csv`. `reports/benchmark_extra_review.json` records query definitions and the absence of organizer extra answer keys.
