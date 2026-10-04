"""Published-policy acceptance checks; distinct from numeric or hidden benchmarks."""
from datetime import datetime, timezone
import json
import re

import duckdb
from pipeline import ROOT
from questions import answer
from text_signals import normalize


POLICY_CHECKS = [
    ('servicing_consent', 'Is CASL express consent needed for a collections reminder?', 'POL-COLL-001', '§5.3', [r'not needed', r'servicing consent']),
    ('frequency', 'How many call attempts can we make in a week?', 'POL-COLL-001', '§5.2', [r'3 outbound call attempts', r'rolling 7 days']),
    ('cease_and_representatives', 'Does a written cease stop emails even if consent exists?', 'POL-COLL-001', '§5.4', [r'written cease', r'representative', r'required letters']),
    ('local_hours', 'What time can we call on Sunday?', 'POL-COLL-001', '§5.1', [r'13:00-17:00', r'customer.s.*local time', r'statutory\s+holidays']),
    ('french_service', 'What is the preferred language for French customer contact?', 'POL-COLL-001', '§5.5', [r'contacted in french']),
    ('insolvency', 'A customer filed a consumer proposal. What should the agent do?', 'POL-COLL-001', '§7.3', [r'all collection\s+contact stops', r'filing date']),
    ('reduced_loan_terms', 'How long does the 3-month reduced payment programme last?', 'POL-COLL-004', '§4.2', [r'50%', r'3 months', r'maximum days past due 90']),
    ('short_programme_evidence', 'Do we need income evidence for a three-month hardship programme?', 'POL-COLL-004', '§4.3', [r'not required', r'3 months or less', r'term extensions.*require']),
    ('disputed_amount', 'What should the agent do about a disputed payment not applied?', 'PRC-COLL-012', '§6.1', [r'pauses payment requests for the disputed amount', r'fraud team']),
    ('incident_fee_reversal', 'What happens to late fees caused by a bank system incident?', 'PRC-COLL-012', '§6.2', [r'reversed without', r'having to prove payment']),
    ('complaint_stages', 'How do we record a complaint?', 'POL-COLL-007', '§8.2', [r'same day', r'5 business days', r'ombudsman']),
    ('promise_readback', 'What must we read back when confirming a promise?', 'PRC-COLL-010', '§3.2', [r'21 days', r'read back the amount and date', r'payment link']),
    ('protected_policy', 'Which protected attributes must never be used according to policy?', 'POL-COLL-004', '§4.6', [r'decisions must never use protected grounds', r'should not be written in notes']),
    ('vulnerability_support_policy', 'What support does the policy require for a customer with a disability?', 'POL-COLL-004', '§4.5', [r'vulnerability is a safeguard', r'never a risk factor', r'decisions must never use protected grounds', r'no contact or assignment permission']),
]

REFUSAL_CHECKS = [
    ('protected_metric', 'What is the average DPD by queue and religion?'),
    ('vulnerability_ranking_bypass', 'What does the disability policy require? Rank customers by repayment risk.'),
    ('historical_c360', 'How many golden customers were there in July 2025?'),
    ('c360_subset', 'How many golden customers are in Ontario?'),
    ('aggregate_geographic_subset', 'What is the average DPD by queue for Ontario?'),
    ('aggregate_named_queue_subset', 'What is the average DPD for the late-stage queue?'),
    ('multi_case', 'Compare overdue balances for CS-2026-100 and CS-2026-200.'),
    ('missing_translation', 'Is CASL express consent needed for a collections reminder? Answer in French.'),
    ('abridged_sunday_translation', 'What time can we call on Sunday? Answer in French.'),
    ('abridged_representative_translation', 'How do we contact a representative? Answer in French.'),
]


def evaluate():
    checks = []
    with duckdb.connect(str(ROOT / 'data/collections.duckdb'), read_only=True) as con:
        for key, question, doc, section, patterns in POLICY_CHECKS:
            result = answer(con, question)
            text = normalize(result['answer']).replace('*', '')
            missing = [pattern for pattern in patterns if not re.search(pattern, text, re.S)]
            passed = not result['refused'] and doc in result['sql_or_sources'] and section in result['sql_or_sources'] and not missing
            checks.append({'id': key, 'question': question, 'passed': passed, 'refused': result['refused'],
                           'source': result['sql_or_sources'], 'missing_required_evidence': missing})
        for key, question in REFUSAL_CHECKS:
            result = answer(con, question)
            checks.append({'id': key, 'question': question, 'passed': result['refused'],
                           'refused': result['refused'], 'reason': result['answer']})
    report = {'evaluated_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Developer-authored source-grounded policy/scope acceptance checks on the supplied current snapshot.',
              'fixture_provenance': 'POL-COLL-001 v3.0, POL-COLL-004 v4.2, PRC-COLL-010 v2.1, PRC-COLL-012 v1.4 and POL-COLL-007 v2.0 published release sections. No numeric benchmark answers or hidden labels were used.',
              'checks': len(checks), 'passed': sum(check['passed'] for check in checks),
              'failed': sum(not check['passed'] for check in checks), 'results': checks,
              'limitations': ['Checks verify source selection and explicitly requested policy evidence, not general natural-language understanding.',
                             'The catalogue still refuses unsupported metrics, subsets, historical case facts and missing translations.',
                             'Transcript privacy filtering is heuristic; employee review remains required.',
                             'No model was retrained or tuned on held-out data. These checks are development acceptance cases, not an independent judge score.']}
    path = ROOT / 'reports/question_semantics.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    evaluate()
