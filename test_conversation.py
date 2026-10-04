"""Checks for classifier partition leakage and conversation disclosure/hold safeguards."""
from datetime import date,time
import unittest
from unittest.mock import patch

from conversation import assist
from train_classifier import fit, grouped_split, predict
from calls import qa_evidence
from speech import word_error
from decisions import recommend
from datetime import datetime, timezone


class ConversationChecks(unittest.TestCase):
    def test_closed_and_unknown_status_and_language_pause_payment_requests(self):
        bundle={'case':{'case_id':'CASE1','case_status':'cured'},'controls':{'preferred_language':'EN'},
            'features':{'action_eligibility':'requires_live_policy_check','definition_version':'test','as_of_date':date(2026,9,28)}}
        with patch('conversation.policy_answer',return_value={'answer':'Policy','sql_or_sources':'policy','refused':False}):
            for status in ('cured','closed',None):
                bundle['case']['case_status']=status
                result=assist(None,bundle,'I want to discuss payment',True,use_model=False)
                self.assertTrue(result['payment_request_paused'])
                self.assertEqual(result['reply_kind'],'closed')
                self.assertNotIn('what is preventing payment',result['suggested_reply'])
                self.assertFalse(any('Any proposed payment amount' in p for p in result['employee_prompts']))
            bundle['case']['case_status']='open'
            self.assertTrue(assist(None,bundle,'Please help',False,use_model=False)['payment_request_paused'])
            bundle['controls']['preferred_language']=None
            result=assist(None,bundle,'Please help',True,use_model=False)
            self.assertTrue(result['payment_request_paused'])
            self.assertIsNone(result['reply_language'])
            self.assertEqual(result['reply_kind'],'employee_language_review')

    def test_french_reply_and_policy_sources_preserve_verification_and_hold_rules(self):
        bundle={'case':{'case_id':'CASE1','case_status':'open'},'controls':{'preferred_language':'FR'},
            'features':{'action_eligibility':'requires_live_policy_check','definition_version':'test','as_of_date':date(2026,9,28)}}
        with patch('conversation.policy_answer',return_value={'answer':'Policy','sql_or_sources':'policy','refused':False}) as retrieve:
            result=assist(None,bundle,"J'ai perdu mon emploi",True,use_model=False)
            self.assertEqual(result['reply_language'],'FR')
            self.assertIn('options de soutien',result['suggested_reply'])
            self.assertEqual({call.args[1] for call in retrieve.call_args_list if call.kwargs.get('language')=='FR'},{'POL-COLL-001-FR','POL-COLL-004-FR'})
            result=assist(None,bundle,'Bonjour',False,use_model=False)
            self.assertIn('vérification de votre identité',result['suggested_reply'])
            self.assertTrue(result['payment_request_paused'])
            bundle['features']['action_eligibility']='hold_insolvency'
            self.assertIn('restrictions de communication',assist(None,bundle,'Bonjour',True,use_model=False)['suggested_reply'])
        with patch('conversation.policy_answer',return_value={'answer':'Unavailable','sql_or_sources':'none','refused':True}):
            result=assist(None,bundle,'Bonjour',True,use_model=False)
            self.assertTrue(result['payment_request_paused'])
            self.assertIn('ne peut pas être vérifiée',result['suggested_reply'])

    def test_recorded_hardship_is_reviewed_separately_from_current_speech(self):
        bundle={'case':{'case_id':'CASE1','case_status':'open','hardship_flag':True},'controls':{'preferred_language':'EN'},'features':{'action_eligibility':'requires_live_policy_check','definition_version':'test','as_of_date':date(2026,9,28)}}
        with patch('conversation.policy_answer',return_value={'answer':'Policy','sql_or_sources':'policy','refused':False}) as retrieve:
            result=assist(None,bundle,'I can afford the payment',True,use_model=False)
        self.assertFalse(result['signals']['hardship'])
        self.assertTrue(result['recorded_hardship_review'])
        self.assertIn('confirm whether support is still needed',result['suggested_reply'])
        self.assertIn('POL-COLL-004',[call.args[1] for call in retrieve.call_args_list])
        self.assertIn('case:CASE1',result['sources'])

    def test_channel_cost_and_language_capacity_routing(self):
        import duckdb
        bundle={'case':{'case_id':'CASE1','case_status':'open','hardship_flag':True,'contact_cap_7d':3},
            'features':{'action_eligibility':'requires_live_policy_check','hardship_mention':True,'as_of_date':date(2026,9,28),
                'definition_version':'test','channel_rpc_rate_90d':'{"call":0.5,"sms":0.1,"email":0.2}'},
            'controls':{'consent_call':True,'consent_sms':True,'consent_email':True,'do_not_call':False,
                'time_zone':'America/Toronto','permitted_start':time(7),'permitted_end':time(21),'preferred_language':'FR'},'attempt_times':[]}
        with duckdb.connect() as con:
            con.execute('CREATE SCHEMA raw; CREATE TABLE raw.channel_capacity(channel VARCHAR,date DATE,unit_cost_cad DOUBLE,outage_flag BOOLEAN,time_band VARCHAR,capacity_units INTEGER,used_units INTEGER)')
            con.execute("INSERT INTO raw.channel_capacity VALUES ('call','2026-09-28',2.4,false,'08-12',100,0),('sms','2026-09-28',0.01,false,'all_day',100,0),('email','2026-09-28',0.001,false,'all_day',100,0)")
            con.execute('CREATE SCHEMA curated; CREATE TABLE curated.contacts(case_id VARCHAR,channel VARCHAR,direction VARCHAR,rpc_flag BOOLEAN,contact_ts_utc TIMESTAMP)')
            for channel,successes in [('call',10),('sms',2),('email',4)]:
                for i in range(20):
                    con.execute("INSERT INTO curated.contacts VALUES ('CASE1',?,'outbound',?,'2026-09-27 15:00:00')",[channel,i<successes])
            con.execute('CREATE TABLE raw.agents(agent_id VARCHAR,status VARCHAR,skill_hardship INTEGER,languages JSON,max_concurrent_cases INTEGER,current_case_load INTEGER)')
            con.execute('''INSERT INTO raw.agents VALUES ('FR-OK','active',4,'["FR","EN"]',10,4),('EN-ONLY','active',5,'["EN"]',10,0),('FR-FULL','active',5,'["FR"]',10,10),('FR-INACTIVE','inactive',5,'["FR"]',10,0)''')
            con.execute("ALTER TABLE raw.agents ADD COLUMN site VARCHAR; ALTER TABLE raw.agents ADD COLUMN vulnerable_customer_certified VARCHAR")
            con.execute("UPDATE raw.agents SET site='Montreal',vulnerable_customer_certified='true'")
            when=datetime(2026,9,28,15,tzinfo=timezone.utc)
            proposal=recommend(con,bundle,when)
            self.assertEqual(proposal['suggested_channel'],'email')
            self.assertEqual([a['agent_id'] for a in proposal['routing_candidates']],['FR-OK'])
            self.assertIsNone(recommend(con,bundle,when.replace(day=29))['suggested_channel'])
            self.assertNotIn('executed',proposal)

    def test_hold_blocks_channel_and_agent_proposals(self):
        bundle={'case':{'case_id':'CASE1','case_status':'open','hardship_flag':False,'contact_cap_7d':3},
            'features':{'action_eligibility':'hold_insolvency','as_of_date':date(2026,9,28),'definition_version':'test','channel_rpc_rate_90d':'{}'},
            'controls':{'consent_call':True,'consent_sms':True,'consent_email':True,'time_zone':'America/Toronto'},'attempt_times':[]}
        with patch('decisions.records',return_value=[{'cost':1}]):
            proposal=recommend(None,bundle,datetime(2026,9,28,15,tzinfo=timezone.utc))
        self.assertIsNone(proposal['suggested_channel'])
        self.assertFalse(proposal['routing_candidates'])
        self.assertTrue(all(not c['eligible'] for c in proposal['channel_candidates']))
    def test_audio_error_and_qa_disclosure_order(self):
        self.assertEqual(word_error('one two three','one three')['edits'],1)
        self.assertIsNone(word_error('','hello')['wer'])
        turns=[{'speaker':'agent','start_sec':1,'text':'Your past due amount is $100'},
            {'speaker':'agent','start_sec':5,'text':'Please confirm your date of birth'},
            {'speaker':'customer','start_sec':8,'text':'I lost my job'},
            {'speaker':'agent','start_sec':10,'text':'We will garnish your wages tomorrow'}]
        results={r['item_code']:r for r in qa_evidence(turns)}
        self.assertEqual(results['identity_verified_before_disclosure']['status'],'potential_issue')
        self.assertEqual(results['no_threatening_language']['status'],'potential_issue')
        # The customer turn immediately follows a DOB prompt without a financial-topic reset.
        # It stays outside generated financial evidence instead of leaking a verification response.
        self.assertEqual(results['hardship_handled_per_policy']['status'],'applicability_needs_review')
    def test_split_keeps_customers_and_duplicates_together(self):
        rows=[{'id':str(i),'customer':str(i//2),'text':'duplicate' if i<3 else 'text '+chr(97+i)} for i in range(30)]
        train,test,_=grouped_split(rows)
        self.assertTrue(train and test)
        locations={row['id']:name for name,group in [('train',train),('test',test)] for row in group}
        self.assertEqual(locations['0'],locations['2'])

    def test_training_learns_signal_and_handles_unsupported_class(self):
        rows=[{'text':text,'labels':{'hardship':flag,'dispute':False,'cease':False,'insolvency':False}} for text,flag in [('lost job no income',True),('lost job reduced income',True),('payment completed thank you',False),('payment completed receipt',False)]]
        model=fit(rows)
        self.assertTrue(predict('lost job',model)['hardship']['flag'])
        self.assertFalse(predict('payment completed',model)['hardship']['flag'])
        self.assertIsNone(predict('something',model)['cease']['flag'])

    def test_identity_disclosure_dispute_and_policy_failure(self):
        bundle={'case':{'case_id':'CASE1','case_status':'open'},'controls':{'preferred_language':'EN'},'features':{'action_eligibility':'requires_live_policy_check','definition_version':'test','as_of_date':date(2026,9,28)}}
        policy={'answer':'Verified policy','sql_or_sources':'policy:test','refused':False}
        with patch('conversation.policy_answer',return_value=policy):
            result=assist(None,bundle,'I dispute this charge',use_model=False)
            self.assertIn('identity verification',result['suggested_reply'])
            self.assertTrue(result['payment_request_paused'])
            result=assist(None,bundle,'I lost my job',True,use_model=False)
            self.assertIn('support options',result['suggested_reply'])
            self.assertTrue(result['requires_human_review'])
            result=assist(None,bundle,'Stop calling me',True,use_model=False)
            self.assertTrue(result['payment_request_paused'])
            self.assertIn('specialist',result['suggested_reply'])
            bundle['features']['action_eligibility']='dispute_review'
            self.assertTrue(assist(None,bundle,'Please help',True,use_model=False)['payment_request_paused'])
            bundle['features']['action_eligibility']='representative_review'
            self.assertIn('specialist',assist(None,bundle,'Please help',True,use_model=False)['suggested_reply'])
        with patch('conversation.policy_answer',return_value={'answer':'Unavailable','sql_or_sources':'none','refused':True}):
            self.assertTrue(assist(None,bundle,'Please help',True,use_model=False)['payment_request_paused'])
        with self.assertRaises(ValueError):
            assist(None,bundle,'')

    def test_short_utterance_denials_do_not_become_hardship(self):
        bundle={'case':{'case_id':'CASE1','case_status':'open'},'controls':{'preferred_language':'EN'},'features':{'action_eligibility':'requires_live_policy_check','definition_version':'test','as_of_date':date(2026,9,28)}}
        with patch('conversation.policy_answer',return_value={'answer':'Policy','sql_or_sources':'policy','refused':False}):
            for statement in ['No hardship reported','I have not lost my job','I can afford the payment']:
                result=assist(None,bundle,statement,True)
                self.assertFalse(result['signals']['hardship'],statement)
            self.assertTrue(assist(None,bundle,'No hardship previously, but now I lost my job',True)['signals']['hardship'])


if __name__=='__main__':
    unittest.main()
