"""Regression checks for ambiguous identity evidence and financial join errors."""
from datetime import date
import unittest
import tempfile
import json
from pathlib import Path

import duckdb

from pipeline import ROOT, verify, build, sql_literal


FIELDS = {
    'customers': 'crm_customer_id duplicate_of_crm_id first_name middle_name last_name date_of_birth primary_phone_e164 primary_phone_raw is_deleted record_hash',
    'card_accounts': 'card_account_id src_customer_ref cardholder_name_raw cardholder_dob_raw cardholder_phone_raw snapshot_date current_balance past_due_amount dpd last_payment_date account_status record_hash',
    'loan_accounts': 'loan_id src_customer_ref borrower_name_raw borrower_dob_raw borrower_phone_raw snapshot_date total_outstanding past_due_amount dpd last_payment_date record_hash',
    'deposit_accounts': 'deposit_account_id src_customer_ref holder_name_raw holder_dob_raw holder_phone_raw snapshot_date currency current_balance overdraft_dpd account_status record_hash',
    'collections_cases': 'case_id coll_customer_ref case_open_date case_status primary_account_id primary_product account_ids current_bucket queue assigned_agent_id current_dpd total_overdue current_ptp_id hardship_flag cease_contact_flag insolvency_hold_flag deceased_hold_flag dispute_flag contact_cap_7d record_hash',
    'contact_history': 'contact_id case_id crm_customer_id account_id direction channel channel_v2 contact_ts_utc rpc_flag outcome_code contact_cost_cad record_hash',
    'promises_to_pay': 'ptp_id case_id crm_customer_id account_id ptp_status ptp_created_ts ptp_due_date status_ts ptp_amount amount_paid_against',
    'agent_notes': 'note_id case_id crm_customer_id account_id note_ts_utc note_text',
    'call_transcripts': 'transcript_id contact_id case_id crm_customer_id call_start_ts file_path',
}


class FoundationChecks(unittest.TestCase):
    def test_rebuild_invalidates_features_and_failed_build_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            release=base/'release'
            (release/'schema').mkdir(parents=True)
            (release/'data').mkdir()
            schema={}
            for table,fields in FIELDS.items():
                path=release/'data'/f'{table}.csv'
                self.con.execute(f'COPY raw.{table} TO {sql_literal(path.as_posix())} (HEADER,FORMAT CSV)')
                schema[table]={'format':'csv','path':f'data/{table}.csv','rows':self.con.execute(f'SELECT count(*) FROM raw.{table}').fetchone()[0],
                    'columns':[{'name':name} for name in fields.split()]}
            (release/'schema/schema.json').write_text(json.dumps(schema),encoding='utf-8')
            database=base/'snapshot.duckdb'
            with duckdb.connect(str(database)) as con:
                con.execute("CREATE SCHEMA features; CREATE TABLE features.case_current AS SELECT 'old' AS version")
            build(release,database,base/'reports')
            with duckdb.connect(str(database)) as con:
                self.assertEqual(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='features'").fetchone()[0],0)
                con.execute("CREATE TABLE features.case_current AS SELECT 'current' AS version")
                expected=con.execute('SELECT count(*) FROM golden.c360').fetchone()[0]
                # A reopened database has no build-session variables, but provenance still serves.
                self.assertEqual(con.execute('SELECT count(*) FROM curated.transcripts').fetchone()[0],2)
            # Make every card unusable in the temporary release. The build must roll back.
            broken=release/'data/card_accounts.csv'
            self.con.execute(f"COPY (SELECT * REPLACE ('bad' AS current_balance) FROM raw.card_accounts) TO {sql_literal(broken.as_posix())} (HEADER,FORMAT CSV)")
            with self.assertRaises(RuntimeError):
                build(release,database,base/'failed-reports')
            with duckdb.connect(str(database),read_only=True) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM golden.c360').fetchone()[0],expected)
                self.assertEqual(con.execute('SELECT version FROM features.case_current').fetchone()[0],'current')

    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect()
        for schema in ('raw', 'restricted', 'curated', 'golden'):
            cls.con.execute(f'CREATE SCHEMA {schema}')
        cls.con.execute("SET VARIABLE snapshot_date=DATE '2026-09-28'")
        for table, fields in FIELDS.items():
            columns = ','.join(f'{name} VARCHAR' for name in fields.split())
            cls.con.execute(f'CREATE TABLE raw.{table}({columns})')

        def add(table, **values):
            fields = FIELDS[table].split()
            cls.con.execute(f"INSERT INTO raw.{table} VALUES ({','.join('?' for _ in fields)})",
                            [values.get(field) for field in fields])

        for key, dob, duplicate, first in [('A', '1990-02-07', None, 'Alice'),
                                           ('B', '1990-07-02', None, 'Alice'),
                                           ('D', '1990-02-07', 'A', 'Alice'),
                                           ('E', '1990-02-07', 'A', 'Eve')]:
            add('customers', crm_customer_id=key, duplicate_of_crm_id=duplicate,
                first_name=first, last_name='Stone', date_of_birth=dob,
                primary_phone_e164='+14165550123', is_deleted='false')
        card = dict(src_customer_ref='CARD-A', cardholder_name_raw='STONE/ALICE',
                    cardholder_dob_raw='1990-02-07', cardholder_phone_raw='416-555-0123',
                    snapshot_date='2026-09-28', current_balance='100', past_due_amount='10', dpd='7')
        add('card_accounts', card_account_id='C1', **card)
        add('card_accounts', card_account_id='C1', **card)  # Exact duplicate.
        add('card_accounts', card_account_id='C2', **(card | {'src_customer_ref': 'AMBIG', 'cardholder_dob_raw': '07-02-1990'}))
        add('card_accounts', card_account_id='C3', **(card | {'src_customer_ref': 'MASKED', 'cardholder_phone_raw': '416555xxx3'}))
        add('card_accounts', card_account_id='C4', **(card | {'past_due_amount': '-10'}))
        add('card_accounts', card_account_id='C5', **card)
        add('card_accounts', card_account_id='C5', **(card | {'current_balance': '999'}))
        add('loan_accounts', loan_id='L1', src_customer_ref='LOAN-A', borrower_name_raw='Alice Stone',
            borrower_dob_raw='1990/02/07', borrower_phone_raw='(416) 555 0123',
            snapshot_date='2026-09-28', total_outstanding='200', past_due_amount='20', dpd='7')
        add('deposit_accounts', deposit_account_id='DEP1', src_customer_ref='0000000001', holder_name_raw='STONE A',
            holder_dob_raw='19900207', holder_phone_raw='4165550123', snapshot_date='2026-09-28',
            currency='CAD', current_balance='5000', overdraft_dpd='0')
        case = dict(case_open_date='2026-09-01', case_status='open', primary_product='card',
                    current_dpd='7', total_overdue='30', hardship_flag='true',
                    account_ids='["C1","L1"]', current_bucket='1-30')
        add('collections_cases', case_id='CASE1', coll_customer_ref='D', **case)
        add('collections_cases', case_id='CASE2', coll_customer_ref='MISSING', **case)
        for key, channel, channel_v2, crm in [('T1', None, 'call', 'D'), ('T2', 'call', 'sms', 'D'), ('T3', 'call', None, 'B')]:
            add('contact_history', contact_id=key, case_id='CASE1', crm_customer_id=crm, channel=channel,
                channel_v2=channel_v2, contact_ts_utc='2026-09-28 12:00:00', direction='outbound',
                rpc_flag='false', outcome_code='NA', contact_cost_cad='1')
        add('promises_to_pay', ptp_id='P1', case_id='CASE1', crm_customer_id='D', ptp_status='kept',
            ptp_created_ts='2026-09-01 12:00:00', ptp_due_date='2026-09-20', ptp_amount='30', amount_paid_against='30')
        for promise,status,due,observed in [
                ('FUTURE-STATUS','kept','2026-09-28','2026-09-29 12:00:00'),
                ('INVALID-STATUS','kept','2026-09-28','not-a-timestamp'),
                ('PRE-CREATION-STATUS','kept','2026-09-28','2026-09-26 12:00:00'),
                ('FUTURE-DUE','open','2026-10-02','2026-09-28 12:00:00')]:
            add('promises_to_pay',ptp_id=promise,case_id='CASE1',crm_customer_id='D',
                ptp_status=status,ptp_created_ts='2026-09-27 12:00:00',ptp_due_date=due,
                status_ts=observed,ptp_amount='30',amount_paid_against='0')
        add('agent_notes', note_id='N1', case_id='CASE1', crm_customer_id='D',
            note_ts_utc='2026-09-28 12:00:00', note_text='Customer requested a callback.')
        # A valid CRM-to-case link cannot make another customer's account evidence safe.
        add('card_accounts', card_account_id='FOREIGN', **(card | {
            'src_customer_ref':'CARD-B', 'cardholder_dob_raw':'1990-07-02'}))
        add('contact_history', contact_id='FOREIGN-CONTACT', case_id='CASE1', crm_customer_id='D',
            account_id='FOREIGN', direction='outbound', channel='call',
            contact_ts_utc='2026-09-28 12:00:00', rpc_flag='true', contact_cost_cad='1')
        add('promises_to_pay', ptp_id='FOREIGN-PTP', case_id='CASE1', crm_customer_id='D',
            account_id='FOREIGN', ptp_status='open', ptp_created_ts='2026-09-28 12:00:00',
            ptp_due_date='2026-09-29', ptp_amount='500')
        for note_id,account in [('FOREIGN-NOTE','FOREIGN'),('UNKNOWN-NOTE','UNRESOLVED')]:
            add('agent_notes',note_id=note_id,case_id='CASE1',crm_customer_id='D',account_id=account,
                note_ts_utc='2026-09-28 12:00:00',note_text='Lost job')
        for transcript,contact,crm in [('VALID','T1','D'),('UNKNOWN','MISSING','D'),
                ('BAD-CONTACT','T3','D'),('BAD-ACCOUNT','FOREIGN-CONTACT','D'),('BAD-CRM','T1','B')]:
            add('call_transcripts',transcript_id=transcript,contact_id=contact,case_id='CASE1',
                crm_customer_id=crm,call_start_ts='2026-09-28 12:00:00',file_path=transcript+'.json')
        add('call_transcripts',transcript_id='FUTURE',contact_id='T1',case_id='CASE1',
            crm_customer_id='D',call_start_ts='2026-09-29 12:00:00',file_path='future.json')
        cls.con.execute((ROOT / 'sql' / 'foundation.sql').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_ambiguous_dob_and_masked_phone_do_not_force_a_match(self):
        self.assertEqual(self.con.execute("SELECT dob_candidates('07-02-1990')").fetchone()[0], [date(1990, 2, 7), date(1990, 7, 2)])
        self.assertIsNone(self.con.execute("SELECT norm_phone('416555xxx3')").fetchone()[0])
        rows = self.con.execute("SELECT source_key,status FROM restricted.identity_map WHERE source_key IN ('AMBIG','MASKED') ORDER BY 1").fetchall()
        self.assertEqual(rows, [('AMBIG', 'quarantined'), ('MASKED', 'quarantined')])

    def test_duplicate_pointer_requires_consistent_identity(self):
        rows = self.con.execute("SELECT source_key,golden_customer_id,status FROM restricted.identity_map WHERE source_system='crm' AND source_key IN ('D','E') ORDER BY 1").fetchall()
        self.assertEqual(rows, [('D', 'C360:A', 'accepted'), ('E', None, 'quarantined')])

    def test_financial_totals_survive_duplicates_and_multiple_child_tables(self):
        self.assertEqual(self.con.execute("SELECT credit_loan_outstanding_cad,deposit_balance_cad,linked_cases FROM golden.c360 WHERE golden_customer_id='C360:A'").fetchone(), (300, 5000, 1))
        self.assertEqual(self.con.execute('SELECT count(*) FROM curated.case_accounts').fetchone()[0], 2)
        self.assertEqual(self.con.execute("SELECT count(*) FROM curated.accounts WHERE account_id IN ('C4','C5')").fetchone()[0], 0)

    def test_leading_zeros_and_initial_names(self):
        self.assertEqual(self.con.execute("SELECT source_key,match_confidence FROM restricted.identity_map WHERE source_system='core_banking'").fetchone(), ('0000000001', 'medium'))

    def test_channel_drift_null_codes_and_cross_customer_links(self):
        self.assertEqual(self.con.execute('SELECT contact_id,channel,outcome_code FROM curated.contacts').fetchall(), [('T1', 'call', 'NA')])
        self.assertEqual(self.con.execute("SELECT count(*) FROM curated.cases WHERE case_id='CASE2'").fetchone()[0], 0)

    def test_interaction_account_contradictions_are_quarantined_without_assuming_unknown_ownership(self):
        for table,restricted,key,record in [('contacts','contact_records','contact_id','FOREIGN-CONTACT'),
                ('promises','promise_records','ptp_id','FOREIGN-PTP'),('notes','note_records','note_id','FOREIGN-NOTE')]:
            self.assertEqual(self.con.execute(
                f'SELECT quality_reason FROM restricted.{restricted} WHERE {key}=?',
                [record]).fetchone()[0],'account_customer_mismatch')
            self.assertEqual(self.con.execute(f'SELECT count(*) FROM curated.{table} WHERE {key}=?',[record]).fetchone()[0],0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM curated.notes WHERE note_id='UNKNOWN-NOTE'").fetchone()[0],1)

    def test_transcripts_reject_resolved_bad_contacts_and_preserve_unknown_linkage(self):
        self.assertEqual(self.con.execute(
            'SELECT transcript_id,contact_link_state FROM curated.transcripts ORDER BY transcript_id').fetchall(),
            [('UNKNOWN','unknown'),('VALID','validated')])

    def test_promise_status_cutoff_does_not_reject_legitimate_future_due_dates(self):
        for promise in ['FUTURE-STATUS','INVALID-STATUS','PRE-CREATION-STATUS']:
            self.assertEqual(self.con.execute('SELECT count(*) FROM curated.promises WHERE ptp_id=?',[promise]).fetchone()[0],0)
        self.assertEqual(self.con.execute(
            "SELECT ptp_status,ptp_due_date FROM curated.promises WHERE ptp_id='FUTURE-DUE'").fetchone(),
            ('open',date(2026,10,2)))

    def test_snapshot_integrity(self):
        self.assertEqual(len(verify(self.con)), 13)


if __name__ == '__main__':
    unittest.main()
