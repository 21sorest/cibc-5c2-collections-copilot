"""Checks for cutoff leakage, contact restrictions, audit integrity and AI boundaries."""
from datetime import date,datetime,time,timezone
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from assistant import contact_gate,save_review,support_options
from features import read_case,safe_file
from llm import enhance_summary,validate_facts
from pipeline import ROOT
from questions import answer,month_bounds,financial_call_evidence
from text_signals import extract,redact
from access import add_user,authenticate,authorize_case


class FeatureChecks(unittest.TestCase):
    def test_scoped_customer_questions_require_assignment_and_safe_fields(self):
        actor={'role':'agent','agent_id':'AG1','name':'employee'}
        safe={'case':{'case_id':'CS-2026-1','golden_customer_id':'G1','case_status':'open'},
              'features':{'case_max_dpd':20,'case_overdue_cad':'30.00','definition_version':'test'},
              'customer':{'golden_customer_id':'G1','financial_coverage':'complete'}}
        with duckdb.connect() as con:
            con.execute('CREATE SCHEMA curated; CREATE TABLE curated.cases(case_id VARCHAR,assigned_agent_id VARCHAR)')
            con.execute("INSERT INTO curated.cases VALUES ('CS-2026-1','AG1'),('CS-2026-2','AG2')")
            with patch('questions.load_case',return_value=safe) as load:
                result=answer(con,'Show C360 and overdue balance for CS-2026-1',actor=actor)
                self.assertFalse(result['refused'])
                self.assertEqual(json.loads(result['answer'])['case_overdue_cad'],'30.00')
                self.assertTrue(answer(con,'Show C360 for CS-2026-2',actor=actor)['refused'])
                self.assertEqual(load.call_count,1)
            self.assertTrue(answer(con,'How many golden customers are there?',actor=actor)['refused'])

    def test_sql_windows_ratios_and_unknowns(self):
        with duckdb.connect() as con:
            con.execute('CREATE SCHEMA raw; CREATE SCHEMA restricted; CREATE SCHEMA curated; CREATE SCHEMA features')
            con.execute('CREATE TABLE restricted.identity_map(source_system VARCHAR,source_key VARCHAR,golden_customer_id VARCHAR,status VARCHAR)')
            con.execute("INSERT INTO restricted.identity_map VALUES ('crm','CRM1','G1','accepted')")
            con.execute('CREATE TABLE raw.customers(crm_customer_id VARCHAR,consent_call BOOLEAN,consent_sms BOOLEAN,consent_email BOOLEAN,internal_do_not_call_flag BOOLEAN,cease_communication_flag BOOLEAN,deceased_flag BOOLEAN,bankruptcy_flag BOOLEAN,consumer_proposal_flag BOOLEAN,credit_counselling_agency_flag BOOLEAN,legal_representative_flag BOOLEAN,sunday_contact_permitted BOOLEAN,time_zone VARCHAR,province_code VARCHAR,permitted_call_start_local TIME,permitted_call_end_local TIME,preferred_language VARCHAR)')
            con.execute("INSERT INTO raw.customers VALUES ('CRM1',true,true,true,false,false,false,false,false,false,false,false,'America/Toronto','ON','07:00','21:00','EN')")
            con.execute('CREATE TABLE curated.cases(case_id VARCHAR,golden_customer_id VARCHAR,current_dpd INTEGER,total_overdue_cad DECIMAL(18,2),cease_contact_flag BOOLEAN,insolvency_hold_flag BOOLEAN,deceased_hold_flag BOOLEAN,dispute_flag BOOLEAN,contact_cap_7d INTEGER,account_link_state VARCHAR)')
            con.execute("INSERT INTO curated.cases VALUES ('CASE1','G1',10,30,false,false,false,false,3,'complete'),('CASE2','G2',5,15,false,false,false,false,3,'partial')")
            con.execute('CREATE TABLE curated.accounts(source_system VARCHAR,account_id VARCHAR,golden_customer_id VARCHAR,dpd INTEGER,last_payment_date DATE)')
            con.execute("INSERT INTO curated.accounts VALUES ('cards','C1','G1',20,'2026-09-23'),('core_banking','DEP1','G1',null,null)")
            con.execute("CREATE TABLE curated.case_accounts AS SELECT 'CASE1' AS case_id,source_system,account_id FROM curated.accounts")
            con.execute('CREATE TABLE curated.contacts(case_id VARCHAR,direction VARCHAR,channel VARCHAR,contact_ts_utc TIMESTAMP,rpc_flag BOOLEAN)')
            con.execute("INSERT INTO curated.contacts VALUES ('CASE1','outbound','call','2026-09-21 18:00',false),('CASE1','outbound','call','2026-09-22 18:00',true),('CASE1','internal','system','2026-09-27 18:00',false),('CASE1','outbound','sms','2026-09-29 18:00',true)")
            con.execute('CREATE TABLE curated.promises(case_id VARCHAR,ptp_status VARCHAR,status_ts TIMESTAMP,ptp_due_date DATE,ptp_created_ts TIMESTAMP)')
            con.execute("INSERT INTO curated.promises VALUES ('CASE1','kept','2026-09-25','2026-09-24','2026-09-20'),('CASE1','broken','2026-09-25','2026-09-24','2026-09-20'),('CASE1','partially_kept','2026-09-25','2026-09-24','2026-09-20'),('CASE1','kept','2026-09-29','2026-09-24','2026-09-20'),('CASE1','open','2026-09-27','2026-10-03','2026-09-27')")
            con.execute('CREATE TABLE raw.salary_credit_history(deposit_account_id VARCHAR,crm_customer_id VARCHAR,credit_month VARCHAR,credit_amount_total DOUBLE)')
            con.execute("INSERT INTO raw.salary_credit_history VALUES ('DEP1','CRM1','2026-05',1000),('DEP1','CRM1','2026-06',1000),('DEP1','CRM1','2026-07',1000),('DEP1','CRM1','2026-08',500),('DEP1','CRM1','2026-09',9999)")
            con.execute('CREATE TABLE features.text_evidence(source_id VARCHAR,kind VARCHAR,case_id VARCHAR,event_date DATE,hardship BOOLEAN,callback BOOLEAN,cease BOOLEAN,insolvency BOOLEAN,dispute BOOLEAN)')
            con.execute("INSERT INTO features.text_evidence VALUES ('N1','note','CASE1','2026-09-27',false,true,false,false,false),('N2','note','CASE1','2026-09-29',true,false,false,false,false)")
            con.execute("SET VARIABLE feature_date=DATE '2026-09-28'")
            con.execute((ROOT/'sql/features.sql').read_text(encoding='utf-8'))
            result=read_case(con,'CASE1')
            self.assertEqual(result['case_max_dpd'],20)
            self.assertEqual(result['days_since_payment'],5)
            self.assertEqual(result['contact_attempts_7d'],1)
            self.assertEqual(result['broken_ptp_90d'],1)
            self.assertAlmostEqual(result['kept_ptp_rate_90d'],1/3)
            self.assertEqual(result['open_ptp_days_to_due'],5)
            self.assertAlmostEqual(result['salary_decline_ratio'],0.5)
            self.assertFalse(result['hardship_mention'])
            self.assertTrue(result['callback_request'])
            other=read_case(con,'CASE2')
            self.assertIsNone(other['hardship_mention'])
            self.assertIsNone(other['salary_decline_ratio'])
            self.assertIsNone(other['kept_ptp_rate_90d'])


def bundle():
    return {'case':{'case_status':'open','contact_cap_7d':3},
        'features':{'action_eligibility':'requires_live_policy_check','outbound_calls_7d':0,'as_of_date':date(2026,9,28)},
        'controls':{'consent_call':True,'consent_sms':True,'consent_email':True,'do_not_call':False,'time_zone':'America/Toronto','permitted_start':time(7),'permitted_end':time(21),'sunday_permitted':False},
        'attempt_times':[]}


class WorkflowChecks(unittest.TestCase):
    def test_support_programmes_use_current_product_and_matched_primary_dpd(self):
        columns=['program_id','version','program_name','product_types','policy_section','description',
            'min_hardship_level','max_dpd','min_months_on_book','max_uses_12m','approver_level',
            'excludes_insolvency','excludes_broken_plan_90d','requires_income_evidence','effective_from','effective_to']
        with duckdb.connect() as con:
            con.execute('CREATE SCHEMA raw')
            con.execute('CREATE TABLE raw.hardship_programs('+','.join(name+' VARCHAR' for name in columns)+')')
            row=['CARD','2026','Reduced payment','["card"]','section 4.2','Published reduced-payment terms',
                 'clear','90','6','1','specialist','true','true','false','2026-01-01','2026-12-31']
            insert='INSERT INTO raw.hardship_programs VALUES ('+','.join('?' for _ in columns)+')'
            con.execute(insert,row)
            expired=row.copy();expired[1]='2025';expired[-1]='2025-12-31';con.execute(insert,expired)
            wrong=row.copy();wrong[0]='AUTO';wrong[3]='["auto_loan"]';con.execute(insert,wrong)
            value={'case':{'primary_product':'card','primary_account_id':'C1','insolvency_hold_flag':False},
                'features':{'as_of_date':date(2026,9,28),'case_max_dpd':140},
                'accounts':[{'account_id':'C1','dpd':20},{'account_id':'OTHER','dpd':140}]}
            options=support_options(con,value)
            self.assertEqual(len(options),1)
            self.assertEqual(options[0]['version'],'2026')
            self.assertEqual(options[0]['review_state'],'candidate_pending_eligibility_review')
            self.assertTrue(any('distinct from promises' in v for v in options[0]['remaining_checks']))
            self.assertNotIn('eligible',options[0])
            value['accounts'][0]['dpd']=100
            self.assertEqual(support_options(con,value)[0]['review_state'],'screened_out')
            value['accounts']=[]
            unknown=support_options(con,value)[0]
            self.assertTrue(any('primary-account DPD' in v for v in unknown['remaining_checks']))
            value['case']['insolvency_hold_flag']=True
            self.assertEqual(support_options(con,value)[0]['review_state'],'screened_out')

    def test_threat_denial_does_not_hide_a_later_positive_statement(self):
        from calls import qa_evidence
        def issues(text):
            return {item['item_code']:item['status'] for item in qa_evidence([{'speaker':'agent','start_sec':1,'text':text}])}
        denied=issues('We cannot arrest you. This is not a criminal matter.')
        self.assertEqual(denied['no_threatening_language'],'needs_review')
        self.assertEqual(denied['no_misleading_statements'],'needs_review')
        mixed=issues('We cannot arrest you, but we will garnish your wages tomorrow.')
        self.assertEqual(mixed['no_threatening_language'],'potential_issue')
    def test_identity_responses_are_excluded_when_account_is_mentioned_and_verification_repeats(self):
        turns=[{'speaker':'agent','start_sec':1,'text':'Before discussing your account, please confirm your date of birth.'},
            {'speaker':'customer','start_sec':2,'text':'July 8'},
            {'speaker':'customer','start_sec':3,'text':'1992'},
            {'speaker':'agent','start_sec':4,'text':'The balance is past due.'},
            {'speaker':'customer','start_sec':5,'text':'I lost my job'},
            {'speaker':'agent','start_sec':6,'text':'Please confirm the address on your account.'},
            {'speaker':'customer','start_sec':7,'text':'123 Main Street'},
            {'speaker':'agent','start_sec':8,'text':'We can review a hardship plan'},
            {'speaker':'customer','start_sec':9,'text':'Yes, that works'},
            {'speaker':'customer','start_sec':10,'text':'I dispute this charge because of identity theft.'}]
        summary=' '.join(financial_call_evidence(turns))
        self.assertNotIn('July',summary)
        self.assertNotIn('1992',summary)
        self.assertNotIn('Main Street',summary)
        self.assertNotIn('date of birth',summary)
        self.assertIn('I lost my job',summary)
        self.assertIn('Yes, that works',summary)
        self.assertIn('identity theft',summary)
        self.assertIn('not customer commitment',summary)

    def test_call_summary_excludes_identity_and_keeps_agreement_context(self):
        turns=[{'speaker':'agent','start_sec':1,'text':'Please confirm date of birth'},
            {'speaker':'customer','start_sec':3,'text':'July 8, 1992'},
            {'speaker':'agent','start_sec':5,'text':'I am calling about your account past due'},
            {'speaker':'customer','start_sec':8,'text':'I lost my job'},
            {'speaker':'agent','start_sec':10,'text':'We can review a hardship plan'},
            {'speaker':'customer','start_sec':12,'text':'Yes, that works'}]
        summary=' '.join(financial_call_evidence(turns))
        self.assertNotIn('1992',summary)
        self.assertIn('Yes, that works',summary)
        self.assertIn('not customer commitment',summary)
    def test_attempt_question_does_not_route_to_case_count(self):
        with duckdb.connect() as con:
            con.execute("CREATE SCHEMA raw; CREATE TABLE raw.collections_cases(case_id VARCHAR,current_bucket VARCHAR,outcome VARCHAR,case_status VARCHAR)")
            con.execute("INSERT INTO raw.collections_cases VALUES ('A','1-30',null,'closed'),('B','1-30',null,'open'),('C','1-30','cured','open')")
            con.execute('CREATE TABLE raw.contact_history(case_id VARCHAR,direction VARCHAR,channel VARCHAR,channel_v2 VARCHAR,contact_ts_utc VARCHAR)')
            con.execute("INSERT INTO raw.contact_history VALUES ('A','outbound','call',null,'2026-09-25'),('A','outbound','sms',null,'2026-09-26'),('B','outbound','email',null,'2026-09-27'),('B','outbound','call',null,'2026-09-29'),('B','internal','system',null,'2026-09-27'),('C','outbound','call',null,'2026-09-27')")
            result=answer(con,'How many outbound contact attempts did open cases receive, on average, by current bucket?')
            self.assertEqual(result['rows'],[{'current_bucket':'1-30','attempts_per_case':1.5}])
    def test_password_accounts_and_assignment_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'users.json'
            add_user('employee','test-password-123','agent','AG1',path)
            self.assertNotIn('test-password-123',path.read_text())
            self.assertIsNone(authenticate('employee','wrong',path))
            actor=authenticate('employee','test-password-123',path)
            self.assertEqual(actor['role'],'agent')
            with self.assertRaises(ValueError):
                add_user('employee','another-password','supervisor',path=path)
            with duckdb.connect() as con:
                con.execute("CREATE SCHEMA curated; CREATE TABLE curated.cases(case_id VARCHAR,assigned_agent_id VARCHAR); INSERT INTO curated.cases VALUES ('CASE1','AG1'),('CASE2','AG2')")
                authorize_case(con,actor,'CASE1')
                with self.assertRaises(PermissionError):
                    authorize_case(con,actor,'CASE2')
            self.assertTrue(answer(None,'What is the average DPD by queue?',actor=actor)['refused'])

    def test_contact_gate_rechecks_time_consent_hold_and_rolling_cap(self):
        value=bundle()
        when=datetime(2026,9,28,15,tzinfo=timezone.utc)
        self.assertTrue(contact_gate(value,'call',when)['eligible'])
        self.assertIn('outside_permitted_hours',contact_gate(value,'call',when.replace(hour=3))['reasons'])
        self.assertIn('snapshot_requires_refresh',contact_gate(value,'call',when.replace(day=29))['reasons'])
        value['controls']['consent_call']=None
        self.assertFalse(contact_gate(value,'call',when)['eligible'])
        value['controls']['consent_call']=True
        value['features']['action_eligibility']='hold_insolvency'
        self.assertFalse(contact_gate(value,'email',when)['eligible'])
        value['features']['action_eligibility']='requires_live_policy_check'
        value['attempt_times']=[datetime(2026,9,21,18),datetime(2026,9,22,18),datetime(2026,9,27,18)]
        self.assertIn('call_cap_reached',contact_gate(value,'call',when)['reasons'])
        with self.assertRaises(ValueError):
            contact_gate(value,'call',when.replace(tzinfo=None))

    def test_review_hash_chain_and_edit_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'audit.sqlite'
            brief={'case_id':'CASE1','contact_gate':{'eligible':False},'proposed_step':'Employee review'}
            with self.assertRaises(ValueError):
                save_review('AG1',brief,'edit',audit_path=path)
            save_review('AG1',brief,'accept',audit_path=path)
            save_review('AG1',brief,'reject',reason='Hold',audit_path=path)
            with closing(sqlite3.connect(path)) as db:
                rows=db.execute('SELECT payload,previous_hash,record_hash FROM reviews ORDER BY sequence').fetchall()
            self.assertEqual(rows[1][1],rows[0][2])
            for payload,previous,digest in rows:
                self.assertFalse(json.loads(payload)['executed'])
                self.assertEqual(hashlib.sha256((previous+payload).encode()).hexdigest(),digest)

    def test_text_negation_redaction_and_source_paths(self):
        self.assertFalse(extract('No hardship reported')['hardship'])
        self.assertTrue(extract('Lost my job; please call me back tomorrow')['hardship'])
        self.assertTrue(extract('CB scheduled')['callback'])
        self.assertNotIn('4165551234',redact('Call 4165551234 or x@example.ca'))
        with self.assertRaises(ValueError):
            safe_file(ROOT,'../../outside.txt')

    def test_question_refusal_is_before_query_execution(self):
        for question in ['Export names and phone numbers','Rank by citizenship','What is the weather?','DROP TABLE golden.c360']:
            self.assertTrue(answer(None,question)['refused'])
        self.assertEqual(month_bounds('July-September 2026'),(date(2026,7,1),date(2026,10,1)))

    def test_model_unknown_citations_and_invented_amounts_rejected(self):
        evidence={'case:1':{'total_overdue_cad':'164.77','current_dpd':10}}
        self.assertEqual(len(validate_facts({'facts':[{'source':'case:1','field':'total_overdue_cad','value':'164.77'}]},evidence)),1)
        for fact in [{'source':'case:1','field':'total_overdue_cad','value':'999'},{'source':'unknown','field':'current_dpd','value':'10'},{'source':'case:1','field':'current_dpd','value':'164.77'}]:
            with self.assertRaises(ValueError):
                validate_facts({'facts':[fact]},evidence)

    def test_optional_api_summary_cannot_replace_contact_gate(self):
        value={'case':{'case_id':'CASE1','golden_customer_id':'G1','case_status':'open','current_dpd':10,'total_overdue_cad':'30.00','queue':'review','account_link_state':'complete'},
            'features':{'as_of_date':'2026-09-28','definition_version':'features-v0.1','broken_ptp_90d':0,'contact_attempts_7d':1,'hardship_mention':False,'callback_request':False},
            'customer':{'golden_customer_id':'G1'},'accounts':[],'promises':[]}
        original={'summary':'Original','sources':['case:CASE1'],'contact_gate':{'eligible':False,'reasons':['hold']},'proposed_step':'Review hold'}
        body={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'facts':[{'source':'case:CASE1','field':'current_dpd','value':'10'}]})}]}],'usage':{'total_tokens':10}}
        with patch('llm.settings',return_value={'OPENAI_API_KEY':'test-only','OPENAI_MODEL':'test-model'}),patch('llm.urlopen',return_value=io.BytesIO(json.dumps(body).encode())) as call:
            result=enhance_summary(value,original)
            request=call.call_args.args[0]
            self.assertFalse(json.loads(request.data)['store'])
            self.assertEqual(result['contact_gate'],original['contact_gate'])
            self.assertEqual(result['proposed_step'],original['proposed_step'])
            self.assertEqual(result['generator'],'openai:test-model')


if __name__=='__main__':
    unittest.main()
