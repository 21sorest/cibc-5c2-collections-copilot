# Collections Copilot

Team 5C2's CIBC Collections Hackathon implementation. A local employee workspace connects a customer C360, source-backed questions, 12 shared features and six reviewed assistance workflows: Agent Assist, Next Best Action, channel comparison, staff routing, post-call summary and QA review.

## Required submission files

| Requirement | File |
| --- | --- |
| Code and run instructions | Python modules, SQL, requirements files and this README |
| Architecture diagram | [docs/architecture.png](docs/architecture.png) |
| C360 data contract | [contracts/c360.json](contracts/c360.json) |
| Data quality issues, counts and handling | [reports/data_quality.md](reports/data_quality.md) |
| All benchmark answers | [submission/benchmark_answers.csv](submission/benchmark_answers.csv) |

The benchmark CSV contains all **50 released questions**, including the 15 extras, in the organizer's exact column format: `question_id,answer,sql_or_sources,refused`. It contains 41 answers and 9 refusals; the extra set has 12 answers and 3 privacy/protected-ranking refusals. Answers are generated through the application's question runner, never manually filled. Official extra-answer accuracy is unknown because no extra answer keys were supplied.

The contract adapts release example `DC-COLL-001`. The architecture is a programmatic engineering diagram; its [source](docs/architecture.mmd) and [renderer](docs/render_architecture.py) are included. No image-generation model was used for it.

Generated C360 dataset: [5C2 Collections C360 on Hugging Face](https://huggingface.co/datasets/21sorest/5c2-collections-c360/).

Source datasets, model weights, credentials, working notes and presentation drafts are kept outside Git. The presentation PDF and demo video are separate form deliverables. Two model provenance reports remain because `trained_llm.py` reads their hashes to validate the optional fine-tuned adapter.

## Run locally

Use Python 3.12. Download the organizer's synthetic dataset from [Maple Collections Hackathon](https://huggingface.co/datasets/nuxsh/maple-collections-hackathon) and extract it so the release README and `data/` folder are inside `maple_data/maple_collections_release/`.

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe pipeline.py build
.\.venv\Scripts\python.exe features.py build
.\.venv\Scripts\python.exe train_classifier.py train
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open **http://127.0.0.1:8501**. Example case `CS-2026-614370` demonstrates the case workspace and conversation assistance; `CS-2026-942626` has matched recorded-call evidence for post-call review. This is a local Streamlit application, not a hosted deployment.

On macOS/Linux, use `python3 -m venv .venv` and `.venv/bin/python` for the remaining commands. The database is created at `data/collections.duckdb`. The pipeline accepts `--release PATH` when the extracted dataset is elsewhere. Keep that source directory available because raw tables use file-backed views. The app and the remaining commands use the default database location.

The supplied snapshot is **28 September 2026**. The simulation checkbox demonstrates release-date controls; current-time checks block contact against stale data. No screen sends messages, assigns employees or changes payment arrangements. Reviews record accept/edit/reject decisions separately in `data/reviews.sqlite`.

Without an account file the app clearly identifies demo access. To enable local sign-in, run `python access.py create --user YOUR_USERNAME --role supervisor` in your terminal; it prompts for a password. Agent accounts use `--role agent --agent-id DATASET_AGENT_ID`. Credentials stay in ignored local storage. These accounts are a prototype, not a production identity provider.

## Regenerate benchmarks and verify

After building the foundation and features:

```powershell
.\.venv\Scripts\python.exe questions.py --benchmark --extra benchmark_questions_extra.csv
.\.venv\Scripts\python.exe evaluate_benchmarks.py
.\.venv\Scripts\python.exe -m unittest -v test_pipeline test_workflows test_conversation test_classifier_split test_audio_cache test_llm_grounding test_llm_training test_trained_llm test_review_integrity test_questions test_question_semantics test_preparation_study test_ui test_calls_depth test_decisions_depth test_qa_review test_assistant_depth
```

The runner writes exactly `submission/benchmark_answers.csv`, merges unique question IDs and rejects conflicting IDs. Refusal values are lowercase `true`/`false`. The numeric evaluator checks public development references only; policy and transcript answers require semantic review. The last full implementation run passed 136 tests, and all 12 scored numeric development tables passed. Dataset-backed UI checks are skipped in CI when the dataset is unavailable.

Open-case aggregates use `outcome IS NULL`, including unresolved holds. Promise-kept rate follows the certified metric: fully kept divided by kept, partially kept and broken promises, using requested due dates. The SMS link answer counts distinct outbound SMS payment links sent in the requested period; repeated contact rows do not add links to the denominator. Query definitions and parameters are recorded with each answer.

## Changes from the Phase 1 design

- DuckDB, Streamlit and SQLite implement the local data, interface and review history. PostgreSQL, FastAPI and online deployment were deferred.
- Identity evidence reconciles five source systems. Ambiguous or conflicting links are quarantined. C360 debt excludes deposit balances and reports missing coverage explicitly.
- Shared offline/live feature definitions cover the current snapshot. Historical customer states and training features are not fabricated from current-only facts.
- Questions select trusted parameterized SQL or applicable policy sections. The app does not execute user-supplied or model-generated SQL.
- Agent Assist remains primary. The other five workflows provide explanations, evidence, prerequisite checks and employee review. Suggestions do not establish optimal treatment or certify compliance.
- The AI path includes a team-trained hardship classifier, pretrained Whisper, local Qwen and a fine-tuned factual-format adapter. Deterministic controls retain contact gates, privacy scope and employee decisions.
- The Phase 1 preparation-time improvement target remains unmeasured. Broad conversation accuracy, real-call audio quality and treatment effectiveness are not established by the synthetic development data.

## AI tools used

**Codex** assisted with document analysis, implementation, debugging, regression tests, reviewer subagents, contracts, submission preparation and interface design. Anthropic's frontend-design guidance and Taste Skill's existing-project redesign guidance informed the UI; no third-party executable skill installer was run.

The **team-trained word/bigram classifier** detects possible financial hardship from approved public-labelled text. **Whisper small.en** is a pretrained local transcription model. **Qwen2.5-0.5B-Instruct** is pretrained; our LoRA adapts it to a narrow task selecting three cited case facts. The model was not trained from scratch. Exact source/field/value validation is separate from conversational usefulness, and model outputs require employee review.

An optional **OpenAI Responses API** adapter is implemented but remains untested. No paid application API calls have been made. The default application and benchmark runner work without API credentials. Codex development assistance is separate from the application's runtime AI integrations.

## Optional local AI components

The base application uses deterministic assistance and the local classifier. Optional components need additional dependencies and model downloads, which are not bundled with this repository.

- Audio: install `requirements-audio.txt`, download the organizer's optional voice archive, then use `python speech.py prepare --limit 5` and `python speech.py evaluate --limit 5 --model small.en`. Mixed speakers need employee attribution.
- CPU generation: install `requirements-local-llm.txt`; place the official `Qwen/Qwen2.5-0.5B-Instruct-GGUF` file `qwen2.5-0.5b-instruct-q4_k_m.gguf` in `data/models/`, then run `python evaluate_local_llm.py`. The application verifies the expected model checksum.
- LoRA: use a separate environment with `requirements-training.txt` and compatible CUDA hardware. Commands are `python train_llm.py prepare --robust`, `python train_llm.py download`, `python train_llm.py train`, and `python train_llm.py evaluate --adapter --split test --limit 0`. Training and evaluation code preserves grouped splits; do not tune on final-test outputs. The adapter is available only when its model, corpus, prompt and result provenance agree.
- Paid drafting: copy `.env.example` to ignored `.env`, configure your own API key/model and authorize costs before using the paid button. It sends scoped financial facts to the provider; no credentials or dataset files belong in Git.

## C360 dataset and export

Run `python export_c360.py` to create `data/c360_release/` with the compressed C360, checksum manifest, contract, quality report and dataset card. This command does not upload anything. The team-hosted C360 is available at [5C2 Collections C360](https://huggingface.co/datasets/21sorest/5c2-collections-c360/).
