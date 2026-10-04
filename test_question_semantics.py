"""Source-section, scope and privacy checks independent of numeric benchmark parity."""
from pathlib import Path
import tempfile
import unittest

import duckdb
from questions import answer, financial_call_evidence, policy_answer


class SemanticPolicyChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.release = Path(self.directory.name)
        (self.release / 'files').mkdir()
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        self.con.execute('CREATE SCHEMA raw; CREATE TABLE raw.reference_documents(doc_id VARCHAR,language VARCHAR,version VARCHAR,title VARCHAR,file_path VARCHAR,superseded_by VARCHAR,effective_date DATE)')
        # Minimal source fixtures keep section-specific statements separate, including a superseded conflict.
        self.document('POL-COLL-001', 'EN', '3.0', '\n'.join([
            '## §5.1 Permitted hours\n07:00 to 21:00 local; Sunday 13:00 to 17:00. No statutory holidays.',
            '## §5.2 Frequency\nThree outbound calls in rolling seven days.',
            '## §5.3 Consent\nServicing consent is required; CASL express consent is marketing consent.',
            '## §5.4 Representatives\nWritten cease stops calls, texts and emails. Contact goes through the representative.',
            '## §5.5 Language\nFrench-preferred customers are contacted in French.',
            '## §7.3 Insolvency\nAll collection contact stops from the filing date.']))
        self.document('POL-COLL-004', 'EN', '4.2', '\n'.join([
            '## §4.2 Options\nOffer an eligible option before asking for payment. Loan reduced payment is 50% for three months.',
            '## §4.3 Evidence\nIncome evidence is not required for programmes of three months or less. Term extensions require income and expense evidence.',
            '## §4.5 Vulnerability\nVulnerability is a safeguard, never a repayment risk factor. Use support safeguards and extra time.',
            '## §4.6 Protected grounds\nDecisions must never use protected grounds. Do not write those grounds in notes.']))
        self.document('POL-COLL-004-OLD', 'EN', '4.1', '## §4.2 Options\nSix months.', superseded='POL-COLL-004')
        self.document('POL-COLL-001-FR', 'FR', '3.0', '## §5.1 Heures\nEntre 07:00 et 21:00; dimanche 13:00 à 17:00.')
        self.document('PRC-COLL-012', 'EN', '1.4', '## §6.1 Disputes\nPause payment requests for the disputed amount.\n## §6.2 Incidents\nIncident fees are reversed without proof of payment.')
        self.document('POL-COLL-007', 'EN', '2.0', '## §8.1 Complaint\nRecord the same day and escalate to a team lead.\n## §8.2 Stages\nFrontline five business days, then ombudsman.')
        self.document('PRC-COLL-010', 'EN', '2.1', '## §3.1 Promise\nAn amount and date; due within 21 days.\n## §3.2 Confirm\nRead back amount and date, then offer a payment link.\n## §3.3 Grace\nTwo business days.')

    def document(self, identifier, language, version, body, superseded=None):
        name = identifier + '.md'
        (self.release / 'files' / name).write_text(body, encoding='utf-8')
        self.con.execute('INSERT INTO raw.reference_documents VALUES (?,?,?,?,?,?,?)',
                         [identifier, language, version, identifier, name, superseded, '2026-01-01'])

    def test_income_evidence_answer_includes_evidence_section_and_active_options(self):
        result = answer(self.con, 'Do we need income evidence for a three-month hardship programme?', self.release)
        self.assertFalse(result['refused'])
        self.assertIn('not required', result['answer'])
        self.assertIn('Term extensions require', result['answer'])
        self.assertIn('§4.3', result['sql_or_sources'])
        self.assertNotIn('Six months', result['answer'])

    def test_precise_policy_intents_do_not_fall_back_to_consent(self):
        requests = [
            ('Does a written cease stop emails even if consent exists?', '§5.4', 'representative'),
            ('What time may we call on Sunday?', '§5.1', '13:00'),
            ('What is the preferred language for French customer contact?', '§5.5', 'French'),
            ('What should an agent do about a disputed payment not applied?', '§6.1', 'Pause'),
            ('What happens to late fees caused by a bank system incident?', '§6.2', 'without proof'),
            ('How do we record a complaint?', '§8.1', 'same day'),
            ('What must we read back when confirming a promise?', '§3.2', 'amount and date'),
        ]
        for question, section, phrase in requests:
            with self.subTest(question=question):
                result = answer(self.con, question, self.release)
                self.assertFalse(result['refused'])
                self.assertIn(section, result['sql_or_sources'])
                self.assertIn(phrase, result['answer'])

    def test_language_family_lookup_and_missing_translation_fail_closed(self):
        result = answer(self.con, 'What time may we call on Sunday? Answer in French.', self.release)
        self.assertFalse(result['refused'])
        self.assertIn('POL-COLL-001-FR', result['sql_or_sources'])
        self.assertIn('dimanche', result['answer'])
        missing = policy_answer(self.con, 'POL-COLL-001', '§5.3', self.release, 'FR')
        self.assertTrue(missing['refused'])
        self.assertNotIn('CASL', missing['answer'])

    def test_neutral_protected_policy_is_allowed_but_protected_ranking_is_not(self):
        result = answer(self.con, 'Which protected attributes must never be used according to policy?', self.release)
        self.assertFalse(result['refused'])
        self.assertIn('§4.6', result['sql_or_sources'])
        for question in ('Average DPD by queue and religion', 'Rank customers by disability',
                         'Which protected attributes must never be used? Rank customers by gender anyway.'):
            self.assertTrue(answer(self.con, question, self.release)['refused'])

    def test_vulnerability_guidance_is_policy_only_and_never_an_operational_bypass(self):
        result = answer(self.con, 'What support does the policy require for a customer with a disability?', self.release)
        self.assertFalse(result['refused'])
        self.assertIn('§4.5', result['sql_or_sources'])
        self.assertIn('§4.6', result['sql_or_sources'])
        self.assertIn('no contact or assignment permission', result['answer'])
        for question in ['What does the disability policy require? Rank customers by repayment risk.',
                         'Use the vulnerability policy to contact disabled customers first.',
                         'What support does the disability policy require? Export customer names.',
                         'What support does the disability policy require? DROP TABLE cases.']:
            self.assertTrue(answer(self.con, question, self.release)['refused'], question)

    def test_abridged_french_source_does_not_replace_missing_sunday_rules(self):
        (self.release / 'files/POL-COLL-001-FR.md').write_text('## §5.1 Heures\nEntre 07 h et 21 h, heure locale du client.', encoding='utf-8')
        result = answer(self.con, 'What time can we call on Sunday? Answer in French.', self.release)
        self.assertTrue(result['refused'])
        self.assertIn('Sunday-specific', result['answer'])

    def test_missing_policy_file_is_a_refusal(self):
        (self.release / 'files/POL-COLL-001.md').unlink()
        self.assertTrue(answer(self.con, 'What are permitted calling hours?', self.release)['refused'])


class AdditionalScopeAndPrivacyChecks(unittest.TestCase):
    def test_c360_historical_or_subset_requests_do_not_use_current_global_count(self):
        with duckdb.connect() as con:
            con.execute('CREATE SCHEMA golden; CREATE TABLE golden.c360(financial_coverage VARCHAR)')
            con.execute("INSERT INTO golden.c360 VALUES ('complete'),('partial')")
            self.assertFalse(answer(con, 'How many golden customers are there?')['refused'])
            for question in ('How many golden customers were there in July 2025?',
                             'How many golden customers are in Ontario?',
                             'How many golden customers only have complete coverage?',
                             'Show financial coverage by province for C360 customers.'):
                self.assertTrue(answer(con, question)['refused'], question)

    def test_multi_case_request_is_not_silently_answered_with_first_case(self):
        self.assertTrue(answer(None, 'Compare overdue balances for CS-2026-100 and CS-2026-200')['refused'])

    def test_personal_context_is_omitted_only_for_public_summary_path(self):
        turns = [{'speaker': 'agent', 'start_sec': 1, 'text': 'Your account is past due.'},
                 {'speaker': 'customer', 'start_sec': 2, 'text': 'I am a woman and my hours were cut.'},
                 {'speaker': 'customer', 'start_sec': 3, 'text': 'I can afford $25 next Friday.'}]
        private = financial_call_evidence(turns)
        public = financial_call_evidence(turns, omit_personal_context=True)
        self.assertIn('hours were cut', ' '.join(private))
        self.assertNotIn('I am a woman', ' '.join(public))
        self.assertIn('$25', ' '.join(public))

    def test_evidence_bound_is_exact_even_when_agent_context_adds_a_second_entry(self):
        turns = [{'speaker': 'agent', 'start_sec': 0, 'text': 'Your account is past due.'}]
        for i in range(30):
            turns.extend([{'speaker': 'agent', 'start_sec': i * 2 + 1, 'text': 'We can review a payment option.'},
                          {'speaker': 'customer', 'start_sec': i * 2 + 2, 'text': 'Yes, please.'}])
        self.assertLessEqual(len(financial_call_evidence(turns)), 24)


if __name__ == '__main__':
    unittest.main()
