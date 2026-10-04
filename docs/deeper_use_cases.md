# Additional use-case implementation

This continuation deepens the five workflows beyond their first working versions. They remain local, employee-reviewed hackathon implementations. The data does not establish treatment efficacy, real-time availability or production compliance.

## Next Best Action

The proposal separates non-open cases, stale evidence, holds, unknown language, disputes, hardship, existing promises and ordinary case preparation. It shows the selected action, source-backed reasons, alternatives, missing evidence and whether payment requests are paused. Competing dispute and hardship needs remain visible rather than allowing one to hide the other.

Hardship review includes snapshot-effective programme versions for the case's primary product. A matched primary account supplies the DPD screen; other accounts' DPD does not silently substitute. Published terms are displayed with remaining checks for documented hardship, account tenure, prior programme uses, income evidence, broken hardship-plan history and approval. A broken promise to pay is not treated as a broken hardship plan. Catalogue candidates are not approved customer offers. Catalogue/policy contradictions, including the short-programme evidence exemption and overlapping effective versions, require policy-owner resolution. Recorded insolvency excludes programmes regardless of catalogue flags.

## Channel comparison

Each channel shows approved case-specific attempts, known outcomes, observed right-party-contact rate and a Wilson interval. Unknown outcomes are excluded from the denominator and shown through support counts. Historical customer-local hours are descriptive evidence, not a prediction of the best contact hour.

Capacity and cost must match the current time band. Outages, exhausted capacity and unknown usage block contact-ready recommendations. At least 20 known outcomes are required for the supported preference path; overlapping cost/RPC intervals prevent a unique preference. Sparse data can still appear in a tentative comparison with its unmet prerequisites.

The release has missing channel usage and mostly sparse case-specific histories. A null ready recommendation is expected. Tentative comparisons grant no contact permission. Repeated attempts are correlated, and the statistical intervals do not prove treatment effectiveness. Capacity time bands lack an explicit timezone; their comparison with customer-local time is an assumption requiring operational confirmation.

The frequency safeguard conservatively counts all recorded outbound non-system attempts because automated payment-reminder purpose is not available in the serving data. This can overblock relative to the supplied call/reminder policy. It is disclosed rather than presented as an exact classifier of qualifying reminders.

## Agent routing

Candidates must match the service language, every required specialist skill and valid available snapshot capacity. Auto-loan cases add the product skill alongside stage/specialist needs; missing roster skill columns block assignment proposals. Conflicting duplicate identities, malformed languages, invalid skill values, negative loads, inactive staff and full capacity are excluded. The interface explains exclusions and offers supervisor review when nobody qualifies. Staff comparison considers weakest required skill and utilization, without protected customer attributes.

French routing requires unambiguous Montréal-site evidence under POL-COLL-001 §5.5. Corrupted source city strings remain unknown and are excluded. An approved current-snapshot vulnerability flag gates support certification only; missing/conflicting evidence conservatively requires certified staff without asserting vulnerability. Accepted case/source/customer provenance and extraction cutoff constrain this flag; absent hashes are matched null-safely with those other keys. It never changes repayment prediction or review priority.

Shift availability and acceptance require confirmation. The suggestion does not reserve capacity or reassign the case. Current-time requests against stale data produce no routing recommendation.

## Post-call summary

The latest approved call is selected at or before the employee's supplied review cutoff, bounded by the available release snapshot. The call timestamp and cutoff are visible. Changing the case or cutoff prevents an old draft from being reused.

The summary separates customer situation, explicit customer commitments, issue mentions and proposed follow-ups. Every extracted statement retains timestamped evidence. Identity-verification responses are excluded. Explicit commitments require a customer-owned affirmative statement with an unambiguous amount and literal date; generic assent, conditional proposals, reported speech and agent offers do not establish a promise. Customer proposals can retain terms for confirmation. Relative dates are not silently converted into calendar dates, and no payment promise is created in the source system.

Protected-context omission is heuristic, not comprehensive PII detection. Evidence excerpts still need employee review. Issue mentions are not proof that an issue remains unresolved. The existing financial-evidence bound limits extracted turns, which is disclosed.

## Quality assurance

All ten supplied checklist items show evidence, applicability, observations and uncertainty. Checks distinguish identity prompts from completed verification, notice timing, bank/name/purpose evidence, negated threats, hardship acknowledgment/options/payment ordering, appropriate escalation and customer-grounded payment read-back. Within-turn ordering uses source-turn order and text offsets; distinct turns with equal timestamps remain distinct. Reversed timestamps force temporal checks back to needs_review. Read-back observations compare the latest customer terms and normalize month aliases without inventing a year or relative-date anchor. Proposal mismatches remain unconfirmed review observations. Call-time balance accuracy and programme eligibility remain source-verification tasks.

Employee observations are recorded per item as not reviewed, meets criterion, issue observed, not applicable or cannot determine. A decided finding needs an evidence or applicability note. The original automated observations remain separate and the transcript identifier is retained in the verified review log. No automatic compliance score or disciplinary action is produced.

## Verification and limits

Run the full checks using the module list in `.github/workflows/checks.yml`. Independent fixtures cover privacy, temporal ordering, false commitments, programme versions, sparse outcomes, capacity time bands, invalid rosters, simultaneous specialist needs and review-log integrity. Dataset-backed Streamlit checks exercise both proposal generation and per-item call review.

`reports/decision_safeguards.json` audits actual approved cases across status, safeguard and hardship strata. It measures safeguard behavior, not whether a recommended treatment is optimal. `reports/qa_evaluation.json` reports all ten detector statuses against 447 approved public-labelled calls. Unknown and evidence-found statuses are not counted as compliance passes. Some candidate-issue detectors have low or zero recall, and misleading-statement support is only four positive examples. The report records these limits.

Structured extraction found 174 customer payment proposals in that evaluation, including 58 with an unambiguous amount and literal date. It found no qualifying explicit affirmative commitments, and did not convert those proposals into promises. Extraction coverage does not establish summary correctness. The final rubric and independent benchmarks still determine which improvements deserve priority.

## Semantic and policy continuation

Conversation assistance now pauses payment requests while hardship affordability/options remain unresolved. Offset-aware contact timestamps preserve their UTC instant; malformed history and invalid caps block contact instead of crashing or allowing it.

`reports/question_semantics.json` records developer-authored source-grounded policy/scope acceptance checks. Policy questions can retrieve exact required sections, refuse incomplete translated sections, and distinguish unsupported historical/customer-subset requests. These checks complement the 12 numeric public benchmarks; they are not a blind semantic benchmark.

Hardship potential-issue triage on the same 447 approved public development calls improved from 85.7% precision / 17.6% recall to 96.3% precision / 76.5% recall. Public labels informed development. Other checklist detectors retain low or zero issue recall; all items still require employee review. Summary correctness is tested on independent regression examples, while actual-call extraction coverage is not a correctness score.
