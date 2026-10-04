# User handoff

The local app is available at http://127.0.0.1:8501 while Streamlit is running. The default case is CS-2026-614370. Snapshot-time simulation demonstrates release-date policy checks; current time blocks stale-data contact.

## Demo routes

- Agent Assist: enter a customer statement in Conversation assistance, confirm identity verification only if the employee actually completed it, inspect policy evidence, and record an accept/edit/reject review.
- Next Best Action, channel comparison and agent routing: Decision proposals shows reasons, permitted channels, unknown evidence and snapshot staff capacity. Reviews do not execute contact or reassign cases.
- Post-call summary and QA: use a matched recorded-call case such as CS-2026-942626. All ten QA items require review; the app does not issue a compliance verdict.
- Audio: case CS-2025-272880 has verified sample VS-10054 with local small.en transcription. The audio is mixed speakers. Listen and verify customer statements before copying them into conversation assistance.
- Questions: show average DPD by queue, the reduced-payment policy, and a protected-data export refusal, with sources visible.
- Local generation: Review assistance has a pretrained local Qwen button. It selects typed source/field/value facts; the application verifies exact equality and renders the sentences. A correct partial output is grounded but can still be incomplete. The deterministic brief remains the fallback. The paid button appears only after user configuration and can incur charges.

## Items requiring the user

1. Send the final rubric and extra benchmark CSV. The runner accepts --extra and must generate answers through code.
2. The private repository is connected and committed at https://github.com/21sorest/cibc-5c2-collections-copilot. The cibchack26 invitation is pending acceptance. Push final benchmark updates before the deadline.
3. Upload data/c360_release to Hugging Face using the user's account and add the final link. The Parquet is only 8.3 MB and already has a checksum, contract and quality report.
4. Review the prepared pitch PDF/PPTX, record a video of at most five minutes, and submit the form by 9 PM IST on 4 October 2026.
5. Optionally configure the paid API in ignored .env after authorizing costs. No paid calls have been made.
6. Run the preparation-time study if making the business-improvement claim. The 30% target remains unmeasured.

## Submission files

README.md; docs/architecture.png; contracts/c360.json; reports/data_quality.md; reports/benchmark_answers.csv; reports/classifier_evaluation.json; reports/classifier_fairness.json; speech and local-generation reports; submission pitch draft. Dataset files, model caches, .env and databases are ignored by Git.

Agent Assist is the primary use case. All six are employee-reviewed local implementations with explicit data and evaluation limitations. The trained classifier, pretrained Whisper, baseline Qwen, completed factual-format LoRA and deterministic policies are separate components. No model was trained from scratch.

Latest pitch draft: submission/5C2_pitch_draft_v7.pdf and submission/5C2_pitch_draft_v7.pptx. Earlier numbered drafts are superseded. Model choices and rubric adaptation are documented in docs/model_decisions.md.

## Verified overnight results

Earlier checks covered dataset-backed UI login, assignment, conversation, safe C360 questions, aggregate refusal and logout. Source approval, exact fact rendering and training integrity have since changed; see `docs/overnight_progress.md` for the latest suite results. All 12 supplied numeric development benchmarks passed in the recorded development evaluation. The recorded 35-question runner generated 29 answers and six deliberate refusals without errors; answered does not mean correct. The latest proposal safeguard audit covers 719 approved cases with zero failures of the tested constraints. These reports must be refreshed when relevant data or behavior changes.

The refreshed classifier was trained locally on 678 examples and evaluated on 181 grouped development examples. Customer, normalized text and complete token signatures determine connected groups. Pure hardship precision/recall is 98.61%/98.61%; the live combination is 94.74%/100%, detecting 72 positives with four false positives. The earlier score is superseded because the old split had token overlap. The protected-field audit now covers 181 examples and is not a fairness certification. Authoritative results are in `reports/classifier_evaluation.json` and `reports/classifier_fairness.json`.

Whisper small.en measured 11.22% WER on 100 approved synthetic recordings in the refreshed provenance scope. Transcription of all 1,803 approved recordings completed with 11.02% aggregate WER in 13,699.9 seconds (3.81 hours) of CPU time. See reports/speech_evaluation_small_en_2000.json; the filename records the requested limit, while actual approved sample count is 1,803. The pretrained CPU Qwen report records ten open-case outputs passing typed exact source/field/value checks, with median latency 7.02 seconds. Sentence rendering is deterministic. These checks do not establish usefulness or completeness; independent and hidden benchmarks remain unverified.

## Active local fine-tuning experiment

The separate `.venv-training` environment uses a pinned Qwen checkpoint and rank-8 query/value LoRA adapters. The completed v2 corpus has 1,529 training examples, including hypothetical null and untrusted-note variants, 118 development cases and 117 final-test cases. Targets are generated field-extraction outputs; this teaches a narrow factual format, not collection strategy or human conversation quality.

Training and final evaluation completed. Base and adapter used identical prompts, strict parsing and BF16 CUDA generation; final evaluation occurred only after training choices were fixed. The adapter passed all 468 complete exact-value outputs. The separate stronger source-key development prompt passed 7/10 baseline outputs and 10/10 adapter outputs, so the unchanged-wrapper baseline failure must not be presented as general incapability. See docs/local_llm_training.md and the completed reports for provenance and limits.

Independent review and implementation are continuing under the user's latest authorization. Rubric, account connections, human timing and final recording remain user-dependent. No paid API calls, external publication, automatic customer contact or payment changes occurred.


The local LoRA fine-tune completed on 1,529 synthetic factual-format examples in 721.25 seconds, updating 540,672 adapter parameters. Final evaluation passed 468/468 complete exact-value outputs across 117 customer-separated cases and four variants. Median GPU generation latency was 4.65 seconds, excluding model load. The unchanged baseline passed 0/468 with this wrapper; a stronger source-key prompt passed 7/10 separate development examples, versus 10/10 for the adapter. This demonstrates narrow format adaptation, not general financial reasoning. The optional adapter is enabled only while model, prompt, corpus and result hashes match; deterministic controls and fallback remain. See docs/local_llm_training.md.


## Deeper additional workflows

See docs/deeper_use_cases.md for action alternatives/programme screens, conditional channel comparisons, multi-skill routing, structured call summaries and employee checklist observations. Consolidated checks passed 114 tests; the expanded actual-case safeguard audit covered 719 cases with zero tested failures. The QA report covers 447 approved public-labelled calls and records low/zero detector recall where applicable. Do not claim all checklist issues are reliably detected.
