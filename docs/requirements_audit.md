# Build requirements audit

Source: Build Phase/CIBC Hackathon Build Phase - Instructions.pdf, pages 2-4. Design comparison: System Design Phase/5C2_SystemDesign.pdf, pages 1-6. This audit records implementation and submission gaps; it does not claim hidden-benchmark performance or final approval.

## Mandatory build scope

| Requirement | Current implementation | Remaining scoring risk |
| --- | --- | --- |
| Layer 1: raw to curated to golden C360, five-system identity confidence, quality checks | DuckDB foundation, restricted identity map, quarantine reasons, measured quality report, C360 contract | Refresh final reports/export after provenance changes. Demonstrate one matched case and rejected contradictory records. |
| Layer 2: plain-English questions over C360, SQL/source with every answer, refusals | Scoped case/C360 lookup, trusted aggregate SQL catalogue, current policy retrieval, approved transcript evidence | Unseen phrasing and unsupported metrics are refused. General query interpretation is narrower than the design. All extra questions still need implementation or explicit refusals through the runner. |
| Layer 3: structured and text/voice features, one definition for training and live scoring | Twelve current SQL features; shared text rules and classifier tokenization; same persisted feature rows served to the app | Historical point-in-time feature training is explicitly unsupported. Feature parity is current snapshot parity, not historical availability validation. |
| Layer 4: working model/agent, explanations, human review/override | Agent Assist, deterministic gates, optional local generation; five deeper reviewed workflows with action alternatives/programme screens, channel uncertainty, multi-skill routing, structured summaries and per-item QA observations | See docs/deeper_use_cases.md. Treatment effectiveness, live availability, call-time financial accuracy and broad QA detection remain unverified. No automatic compliance verdict is issued. |
| No protected attributes in decisions; flag financial hardship | Approved financial inputs, protected-field exclusions, hardship support cues, separate limited fairness audit | Synthetic subgroup checks do not establish production fairness; short live speech differs from full labelled notes/calls. |

## Required submission artifacts

| Artifact | Current state | Action still required |
| --- | --- | --- |
| Private GitHub repository; organisers as collaborators; commits throughout | Local Git repository and source files | Account/remote setup, correct commit author, commits and organiser identities. Existing local files are not a submitted private repository. |
| README with run instructions, changes from design and AI-tool disclosure | README and model/design notes exist | Update stale counts/model wording after refreshed results and LoRA experiment; verify a clean-install run. |
| Final architecture PDF or PNG in repository | docs/architecture.png and editable Mermaid source | Keep aligned with the final approved source and generation paths. |
| Golden C360 JSON/YAML contract | contracts/c360.json | Keep exported package contract/report aligned with final rebuild. |
| Measured data-quality report and handling | reports/data_quality.md and quality_summary.json | Include new interaction/transcript provenance exclusions; preserve full data scope and count definitions. |
| Generated benchmark CSV for every original and extra question | questions.py runner and reports/benchmark_answers.csv | Merge organiser extra questions released 4 October at 7 PM IST, regenerate through the system, verify schema and coverage. Never edit answers manually. |
| Demo video, at most five minutes, unlisted YouTube/Drive link | docs/demo_script.md | Human recording and hosting link. Show actual dataset cases, source evidence, refusal and review. |
| Pitch PDF, at most ten slides | Nine-slide v6 draft and editable source | Final team/rubric review. Video and deck are submitted separately from the repository. |
| Submission form by 4 October, 9 PM IST | Not submitted | User/team submits required links. Commits after 9 PM are excluded by the supplied instructions. |

The user reports that generated C360 can be hosted on Hugging Face and linked. The local export package is prepared; publication and the final URL remain separate from code delivery.

## Published judging weights

The build instructions, page 4, already specify Technical quality and working demo 30%, Business understanding 20%, Presentation and storytelling 20%, Innovative ideas 15%, and Team work 15%. Generated benchmark answers contribute to Technical quality and working demo; judges also ask unseen questions live. A later detailed rubric may clarify these categories, but the supplied weights should guide current priorities.

Highest priority: correct generated benchmark answers and provenance, a reliable end-to-end Agent Assist demonstration, final required artifacts, and truthful measured claims. A recorded business-value study would support the design's preparation-time objective, but no 30% savings claim has been measured. More use-case prototypes or extra model training do not automatically earn more points.

## Changes from the system design

DuckDB and local Streamlit replace PostgreSQL/FastAPI serving for this prototype. Trusted SQL replaces LLM-generated SQL and SQLGlot validation. Current-only features replace historical snapshots because source availability/status histories are insufficient. Local rules and a small classifier provide text signals; Whisper and the unchanged Qwen baseline are pretrained. A separate LoRA experiment adapts a pretrained model to narrow factual targets, with results reported separately.

The design proposed customer-wide caps; the supplied POL-COLL-001 section 5.2 instead specifies a maximum of three outbound call attempts per case in a rolling seven days. The prototype follows the supplied policy rather than inventing an additional customer-wide cap.

Design targets still deferred include identity-steward approval workflow, immutable historical feature snapshots with available_at metadata, persistent per-signal corrections feeding approved training, ongoing schema/drift alerts, production identity/TLS/retention controls, and real-time refresh SLAs. These are useful limitations to disclose, not additional mandatory build deliverables in the four-page instructions.

## Source-file consistency check

A read-only scan compared all 25,000 transcript JSON files against their CSV sidecars on transcript_id, case_id, crm_customer_id, contact_id and file_path. No files were missing and no field conflicts were found. All 2,000 voice metadata rows also agree with their transcript's contact_id and reciprocal voice_sample_id. These checks establish supplied-file consistency only; approved case/contact/account ownership still requires curated provenance checks.
