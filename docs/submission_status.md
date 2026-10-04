# Submission status

The local prototype connects all four layers, with a team-trained text classifier, local pretrained speech/language models, a team-trained factual LoRA adapter and employee review. Adapter validation is recorded separately. All six Layer 4 choices are implemented as reviewed local workflows. The five additional workflows have been deepened with explicit evidence, uncertainty, source-dependent prerequisites and independent checks; see docs/deeper_use_cases.md. Agent Assist remains the primary use case. Paid API verification needs user credentials. This is a local hackathon demo.

| Requirement | Current evidence | Remaining work |
| --- | --- | --- |
| Five-system matching, curated data and C360 | reports/data_quality.md, pipeline.py | Review unmatched source coverage |
| Customer contract | contracts/c360.json | Owner/team review before submission |
| Feature registry and one serving definition | contracts/features.json, reports/features_summary.json | Historical training snapshots unsupported |
| Structured and text signals | sql/features.sql, reports/text_evaluation.json | Improve remaining misses and validate independently |
| Questions with SQL/sources and refusals | questions.py, reports/benchmark_answers.csv, reports/question_semantics.json | Broader semantic review and extra questions |
| Layer 4 assistance and employee review | app.py, conversation.py, decisions.py, calls.py, assistant.py | Broader independent evaluation; optional paid API verification |
| Local classifier | train_classifier.py, contracts/text_model.json, reports/classifier_evaluation.json | Hidden-test and short-utterance validation |
| Local speech and generation | speech.py, local_llm.py, measured reports | Speaker attribution and semantic review |
| Human decision history and access scope | Local data/reviews.sqlite, access.py with agent assignment and supervisor roles | Configure accounts and use a production identity provider before deployment |
| Architecture PNG | docs/architecture.png | Update if implementation changes |
| Quality and numeric benchmark evaluation | reports/data_quality.md, reports/benchmark_dev_evaluation.json | Hidden benchmarks are not verified |
| Measured preparation-time improvement | No claim made | Run a timed manual-versus-assisted study |
| Private GitHub repository and commits | Local Git initialized | Configure author, connect account/remote, commit and add organisers |
| Demo video, maximum 5 minutes | docs/demo_script.md | Record and submit a link |
| Pitch deck, maximum 10 slides, PDF | submission/5C2_pitch_draft_v7.pdf, nine slides, with editable PPTX | Final team/rubric review and separate submission |
| Generated C360 hosting | data/c360_release local export with checksum and contract | User-managed Hugging Face upload and final link |

The supplied build instructions set the additional-question release to 4 October 2026 at 7 PM IST, with final submission at 9 PM IST. Benchmark answers must come from the application runner and must not be manually edited.
