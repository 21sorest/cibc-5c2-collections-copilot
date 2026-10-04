"""Policy boundaries for malformed histories and unresolved hardship review."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest
import duckdb

from assistant import contact_gate,support_options
from conversation import assist
from test_workflows import bundle


class AssistantDepthChecks(unittest.TestCase):
    def test_aware_history_offsets_preserve_the_rolling_boundary(self):
        value=bundle()
        when=datetime(2026,9,28,18,tzinfo=timezone.utc)
        # These are 16:00 UTC, outside the seven-day window, even though
        # dropping their +02:00 offset would incorrectly count them at 18:00.
        value['attempt_times']=[datetime(2026,9,21,18,tzinfo=timezone(timedelta(hours=2)))]*3
        self.assertTrue(contact_gate(value,'call',when)['eligible'])
        value['attempt_times']=[when-timedelta(days=7)]*3
        self.assertIn('call_cap_reached',contact_gate(value,'call',when)['reasons'])

    def test_malformed_history_and_cap_block_contact_without_crashing(self):
        when=datetime(2026,9,28,18,tzinfo=timezone.utc)
        for stamps in [None,'unknown',[None],[when,'bad timestamp']]:
            value=bundle();value['attempt_times']=stamps
            self.assertFalse(contact_gate(value,'call',when)['eligible'])
        for cap in [None,0,-1,True,'3',2.5]:
            value=bundle();value['case']['contact_cap_7d']=cap
            self.assertIn('invalid_contact_cap',contact_gate(value,'call',when)['reasons'])

    def test_hardship_does_not_mark_payment_requests_as_ready(self):
        value=bundle()
        value['case'].update(case_id='CASE1',hardship_flag=False)
        value['features'].update(definition_version='test')
        value['controls']['preferred_language']='EN'
        with patch('conversation.policy_answer',return_value={'refused':False,'sql_or_sources':'supplied policy'}):
            result=assist(None,value,'I lost my job and cannot afford the payment.',identity_verified=True,use_model=False)
            self.assertEqual(result['reply_kind'],'hardship')
            self.assertTrue(result['payment_request_paused'])
            value['case']['hardship_flag']=True
            result=assist(None,value,'Hello',identity_verified=True,use_model=False)
            self.assertTrue(result['payment_request_paused'])
            self.assertTrue(result['recorded_hardship_review'])

    def test_programme_evidence_conflicts_require_policy_resolution(self):
        columns=['program_id','version','program_name','product_types','policy_section','description',
                 'min_hardship_level','max_dpd','min_months_on_book','max_uses_12m','approver_level',
                 'excludes_insolvency','excludes_broken_plan_90d','requires_income_evidence',
                 'effective_from','effective_to','duration_months']
        with duckdb.connect() as con:
            con.execute('CREATE SCHEMA raw')
            con.execute('CREATE TABLE raw.hardship_programs('+','.join(c+' VARCHAR' for c in columns)+')')
            row=['SHORT','1','Short programme','["card"]','4.3','Terms','clear','90','6','1',
                 'specialist','true','true','true','2026-01-01','2026-12-31','3']
            con.execute('INSERT INTO raw.hardship_programs VALUES ('+','.join('?' for _ in columns)+')',row)
            value={'case':{'primary_product':'card','primary_account_id':'C1','insolvency_hold_flag':False},
                   'features':{'as_of_date':bundle()['features']['as_of_date']},
                   'accounts':[{'account_id':'C1','dpd':20}]}
            result=support_options(con,value)[0]
            self.assertEqual(result['review_state'],'requires_policy_resolution')
            self.assertIn('§4.3',result['policy_conflicts'][0])
            con.execute("UPDATE raw.hardship_programs SET program_id='HP-LOAN-EXT',duration_months='12',requires_income_evidence='false'")
            result=support_options(con,value)[0]
            self.assertEqual(result['review_state'],'requires_policy_resolution')
            self.assertIn('income and expense',result['policy_conflicts'][0])
            con.execute("UPDATE raw.hardship_programs SET excludes_insolvency='false'")
            value['case']['insolvency_hold_flag']=True
            result=support_options(con,value)[0]
            self.assertEqual(result['review_state'],'screened_out')
            self.assertTrue(any('regardless of catalogue' in text for text in result['exclusion_reasons']))


if __name__=='__main__':
    unittest.main()
