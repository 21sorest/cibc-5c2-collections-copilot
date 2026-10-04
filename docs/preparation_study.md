# Case preparation study protocol

The original design's 30% preparation-time improvement is a target, not a measured result. This protocol needs human participants after they wake up; automated script timing cannot substitute for employee preparation time.

Use four matched pairs of approved cases, with similar overdue amounts, delinquency stage and history length. Have at least two participants alternate the order of manual and assisted tasks to reduce learning effects. Do not reuse the same case for both modes with the same participant. Use a neutral facilitator to choose cases and check answers.

For each case, ask the participant to identify the case overdue amount and DPD, existing promise status, contact restrictions, evidence of hardship, and the applicable support/contact policy. In manual mode use the supplied source records and policy files. In assisted mode use the local app. Start the timer when the case ID is revealed and stop when the participant submits their answers. Include loading and correction time. Do not give them the correct answer in advance.

Record participant code, matched-pair code, mode, case ID, elapsed seconds, correctly answered items, total items, and whether any unsafe suggestion was accepted. Keep names and personal details out of the study log. Save results locally under ignored data/study/.

Compare median time among complete correct tasks, report the number of participants/tasks and errors in each mode, and compute improvement as 100 * (manual median - assisted median) / manual median. Also report all-task timing so excluding incorrect tasks cannot hide poor performance. With such a small pilot, describe the result as exploratory and avoid claiming general bank-wide savings.

The user still needs to run the human tasks, record the demo and approve final presentation wording. No result has been filled in for this study.

Prepared materials are in ignored `data/study/case_pairs.json` and `data/study/results.csv`. The sheet contains 16 blank observations for two participants and four matched pairs, with case, mode and task order counterbalanced. Keep the answer/facilitator packet away from participants. `python preparation_study.py prepare` regenerates assignments and refuses to overwrite an existing filled study. After human tasks, run `python preparation_study.py analyze`. The analyzer validates assignments and paired observations before writing an exploratory report; blank or incomplete observations produce no savings result.
