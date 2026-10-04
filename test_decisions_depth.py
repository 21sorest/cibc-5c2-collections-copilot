"""Independent action-precedence, uncertainty, operational and roster safeguards."""
from datetime import date,datetime,time,timezone
import unittest
import duckdb
from decisions import recommend,wilson


def bundle():
    return {'case':{'case_id':'CASE','case_status':'open','hardship_flag':False,'contact_cap_7d':3},
        'features':{'as_of_date':date(2026,9,28),'definition_version':'test','action_eligibility':'requires_live_policy_check',
            'case_max_dpd':45,'account_coverage':'complete','hardship_mention':False,'callback_request':False,'open_ptp_days_to_due':None},
        'controls':{'preferred_language':'EN','time_zone':'America/Toronto','consent_call':True,'consent_sms':True,'consent_email':True,
            'do_not_call':False,'permitted_start':time(7),'permitted_end':time(21)},'attempt_times':[]}


class DecisionDepthChecks(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect();self.con.execute('CREATE SCHEMA raw; CREATE SCHEMA curated')
        self.con.execute('CREATE TABLE curated.contacts(case_id VARCHAR,channel VARCHAR,direction VARCHAR,rpc_flag BOOLEAN,contact_ts_utc TIMESTAMP)')
        self.con.execute('CREATE TABLE raw.channel_capacity(channel VARCHAR,date DATE,time_band VARCHAR,capacity_units INTEGER,used_units INTEGER,unit_cost_cad DOUBLE,outage_flag BOOLEAN)')
        self.con.execute("INSERT INTO raw.channel_capacity VALUES ('call','2026-09-28','08-12',100,0,2,false),('call','2026-09-28','12-17',100,0,0.001,false),('sms','2026-09-28','all_day',100,0,0.1,false),('email','2026-09-28','all_day',100,0,0.01,false)")
        self.con.execute('CREATE TABLE raw.agents(agent_id VARCHAR,status VARCHAR,languages VARCHAR,max_concurrent_cases VARCHAR,current_case_load VARCHAR,skill_early_stage VARCHAR,skill_mid_stage VARCHAR,skill_late_stage VARCHAR,skill_disputes VARCHAR,skill_hardship VARCHAR)')
        self.con.execute("INSERT INTO raw.agents VALUES ('BOTH','active','[\"EN\"]','10','2','4','4','4','4','4'),('DISPUTE','active','[\"EN\"]','10','0','4','4','4','5','0'),('BAD','active','bad-json','10','0','4','4','4','5','5'),('NEGATIVE','active','[\"EN\"]','10','-1','4','4','4','5','5'),('FULL','active','[\"EN\"]','10','10','4','4','4','5','5')")
        self.con.execute("ALTER TABLE raw.agents ADD COLUMN site VARCHAR; ALTER TABLE raw.agents ADD COLUMN vulnerable_customer_certified VARCHAR")
        self.con.execute("UPDATE raw.agents SET site='Montreal',vulnerable_customer_certified='true'")
        self.when=datetime(2026,9,28,15,tzinfo=timezone.utc)

    def tearDown(self):self.con.close()

    def history(self,count=20):
        for channel in ('call','sms','email'):
            for i in range(count):self.con.execute("INSERT INTO curated.contacts VALUES ('CASE',?,'outbound',?,'2026-09-27 15:00:00')",[channel,i%2==0])

    def test_sparse_samples_are_not_ranked_and_wilson_interval_is_exposed(self):
        self.history(2);result=recommend(self.con,bundle(),self.when)
        self.assertIsNone(result['suggested_channel'])
        self.assertTrue(all(r['evidence_state']=='sparse' for r in result['channel_candidates']))
        self.assertEqual(result['channel_candidates'][0]['known_rpc_count'],2)
        low,high=wilson(1,2);self.assertLess(low,0.5);self.assertGreater(high,0.5)
        self.assertTrue(result['requires_human_review'])

    def test_current_band_cost_and_unknown_exhausted_capacity(self):
        self.history();result=recommend(self.con,bundle(),self.when)
        call=next(r for r in result['channel_candidates'] if r['channel']=='call')
        self.assertEqual(call['snapshot_unit_cost_cad'],2)
        self.assertEqual(result['suggested_channel'],'email')
        self.con.execute("UPDATE raw.channel_capacity SET used_units=NULL WHERE channel='email'")
        pending=recommend(self.con,bundle(),self.when)
        self.assertIsNone(pending['suggested_channel'])
        self.assertEqual(pending['preferred_channel_pending_verification'],'email')
        self.assertEqual(pending['comparison_order'][0]['channel'],'email')
        self.con.execute('UPDATE raw.channel_capacity SET used_units=capacity_units')
        result=recommend(self.con,bundle(),self.when)
        self.assertIsNone(result['suggested_channel'])
        self.assertTrue(all(not r['eligible'] for r in result['channel_candidates']))

    def test_exhausted_cheap_duplicate_cannot_price_an_available_channel(self):
        self.history()
        self.con.execute("UPDATE raw.channel_capacity SET used_units=capacity_units WHERE channel='email'")
        self.con.execute("INSERT INTO raw.channel_capacity VALUES ('email','2026-09-28','all_day',100,0,10,false)")
        result=recommend(self.con,bundle(),self.when)
        email=next(r for r in result['channel_candidates'] if r['channel']=='email')
        self.assertEqual(email['descriptive_snapshot_unit_cost_cad'],0.01)
        self.assertEqual(email['operational_unit_cost_cad'],10)
        self.assertEqual(email['snapshot_unit_cost_cad'],10)
        self.assertEqual(result['suggested_channel'],'sms')
        self.assertEqual(result['comparison_order'][0]['channel'],'email')

    def test_auto_loan_requires_product_skill_and_missing_schema_blocks_routing(self):
        value=bundle();value['case']['primary_product']='auto_loan'
        result=recommend(self.con,value,self.when)
        self.assertEqual(result['routing_requirements']['skills'],['skill_mid_stage','skill_auto_loans'])
        self.assertFalse(result['routing_candidates'])
        self.assertEqual(result['roster_exclusions']['required_skill_schema_missing'],1)
        self.con.execute("ALTER TABLE raw.agents ADD COLUMN skill_auto_loans VARCHAR")
        self.con.execute("UPDATE raw.agents SET skill_auto_loans='0'")
        self.con.execute("UPDATE raw.agents SET skill_auto_loans='3' WHERE agent_id='BOTH'")
        self.assertEqual([r['agent_id'] for r in recommend(self.con,value,self.when)['routing_candidates']],['BOTH'])

    def test_uncertainty_overlap_prevents_a_unique_channel_choice(self):
        self.history();self.con.execute('UPDATE raw.channel_capacity SET unit_cost_cad=0.1')
        result=recommend(self.con,bundle(),self.when)
        self.assertIsNone(result['suggested_channel'])
        self.assertIsNone(result['preferred_channel_pending_verification'])
        self.assertEqual(len(result['comparison_order']),3)
        self.assertTrue(all(r['timing_evidence'][0]['hour_local']==11 for r in result['channel_candidates']))

    def test_missing_outcomes_and_unresolved_callback_do_not_grant_a_channel_choice(self):
        self.history();self.con.execute("INSERT INTO curated.contacts VALUES ('CASE','email','outbound',NULL,'2026-09-27 15:00:00')")
        result=recommend(self.con,bundle(),self.when)
        email=next(r for r in result['channel_candidates'] if r['channel']=='email')
        self.assertEqual(email['missing_rpc_outcomes'],1)
        self.assertEqual(email['evidence_state'],'incomplete_outcomes')
        self.assertIsNone(result['suggested_channel'])
        value=bundle();value['features']['callback_request']=True
        result=recommend(self.con,value,self.when)
        self.assertEqual(result['action_code'],'callback_review')
        self.assertIsNone(result['suggested_channel'])
        self.assertTrue(result['timing_review']['callback_confirmation_required'])
        value=bundle();value['features']['case_max_dpd']=150;value['features']['open_ptp_days_to_due']=3
        self.assertEqual(recommend(self.con,value,self.when)['required_skill'],'skill_late_stage')

    def test_french_site_requires_verified_montreal_and_rejects_corrupt_site(self):
        value=bundle();value['controls']['preferred_language']='FR'
        self.con.execute("UPDATE raw.agents SET languages='[\"FR\"]' WHERE agent_id<>'BAD'")
        self.con.execute("UPDATE raw.agents SET site='Toronto' WHERE agent_id='DISPUTE'")
        result=recommend(self.con,value,self.when)
        self.assertEqual([r['agent_id'] for r in result['routing_candidates']],['BOTH'])
        self.con.execute("UPDATE raw.agents SET site=? WHERE agent_id='BOTH'",['Montr\ufffdal'])
        result=recommend(self.con,value,self.when)
        self.assertFalse(result['routing_candidates'])
        self.assertEqual(result['roster_exclusions']['unknown_or_corrupt_french_site'],1)

    def test_unknown_vulnerability_requires_certification_without_priority_change(self):
        self.history()
        self.con.execute("UPDATE raw.agents SET vulnerable_customer_certified=NULL")
        unknown=recommend(self.con,bundle(),self.when)
        self.assertFalse(unknown['routing_candidates'])
        self.assertIsNone(unknown['suggested_channel'])
        self.assertEqual(unknown['routing_requirements']['vulnerability_safeguard']['state'],'unknown_or_conflicting')
        self.assertEqual(unknown['review_priority'],'standard_case_review')
        self.con.execute("UPDATE raw.agents SET vulnerable_customer_certified='true' WHERE agent_id='BOTH'")
        self.assertEqual([r['agent_id'] for r in recommend(self.con,bundle(),self.when)['routing_candidates']],['BOTH'])

    def test_certification_uses_only_approved_source_case_and_detects_conflicting_flags(self):
        self.con.execute("CREATE SCHEMA restricted")
        self.con.execute("CREATE TABLE curated.cases(case_id VARCHAR,golden_customer_id VARCHAR)")
        self.con.execute("CREATE TABLE restricted.case_records(case_id VARCHAR,source_key VARCHAR,record_hash VARCHAR,golden_customer_id VARCHAR,quality_reason VARCHAR)")
        self.con.execute("CREATE TABLE raw.collections_cases(case_id VARCHAR,coll_customer_ref VARCHAR,record_hash VARCHAR,vulnerable_customer_flag VARCHAR,extract_ts VARCHAR)")
        self.con.execute("INSERT INTO curated.cases VALUES ('CASE','G')")
        self.con.execute("INSERT INTO restricted.case_records VALUES ('CASE','CRM','H','G',NULL)")
        self.con.execute("INSERT INTO raw.collections_cases VALUES ('CASE','CRM','H','false','2026-09-28 04:30:00'),('CASE','WRONG','H','true','2026-09-28 04:30:00'),('CASE','CRM','H','true','2026-09-29 04:30:00')")
        self.con.execute("UPDATE raw.agents SET vulnerable_customer_certified='false'")
        result=recommend(self.con,bundle(),self.when)
        self.assertEqual(result['routing_requirements']['vulnerability_safeguard']['state'],'explicitly_not_recorded')
        self.assertTrue(result['routing_candidates'])
        self.con.execute("INSERT INTO raw.collections_cases VALUES ('CASE','CRM','H','true','2026-09-28 04:30:00')")
        result=recommend(self.con,bundle(),self.when)
        self.assertEqual(result['routing_requirements']['vulnerability_safeguard']['state'],'unknown_or_conflicting')
        self.assertFalse(result['routing_candidates'])
        self.con.execute("DELETE FROM raw.collections_cases WHERE vulnerable_customer_flag='false'")
        result=recommend(self.con,bundle(),self.when)
        self.assertEqual(result['routing_requirements']['vulnerability_safeguard']['state'],'recorded')
        self.assertFalse(result['routing_candidates'])
        self.assertEqual(result['review_priority'],'standard_case_review')
        self.con.execute('UPDATE raw.collections_cases SET record_hash=NULL; UPDATE restricted.case_records SET record_hash=NULL')
        result=recommend(self.con,bundle(),self.when)
        self.assertEqual(result['routing_requirements']['vulnerability_safeguard']['state'],'recorded')

    def test_ephemeral_audit_projection_still_applies_cutoff_and_unknown_state(self):
        self.con.execute("CREATE TEMP TABLE decision_safeguard_inputs(case_id VARCHAR,recorded BOOLEAN,extract_ts TIMESTAMP)")
        self.con.execute("INSERT INTO decision_safeguard_inputs VALUES ('CASE',false,'2026-09-28 04:30:00'),('CASE',true,'2026-09-29 04:30:00'),('OTHER',true,'2026-09-28 04:30:00')")
        self.con.execute("UPDATE raw.agents SET vulnerable_customer_certified='false'")
        result=recommend(self.con,bundle(),self.when)
        self.assertEqual(result['routing_requirements']['vulnerability_safeguard']['state'],'explicitly_not_recorded')
        self.assertTrue(result['routing_candidates'])
        result=recommend(self.con,bundle(),self.when.replace(hour=3))
        self.assertEqual(result['routing_requirements']['vulnerability_safeguard']['state'],'unknown_or_conflicting')
        self.assertFalse(result['routing_candidates'])

    def test_competing_specialist_needs_and_invalid_roster(self):
        value=bundle();value['features']['action_eligibility']='dispute_review';value['case']['hardship_flag']=True
        result=recommend(self.con,value,self.when)
        self.assertEqual(result['action_code'],'dispute_review')
        self.assertTrue(result['payment_request_paused'])
        self.assertEqual(result['routing_requirements']['skills'],['skill_disputes','skill_hardship'])
        self.assertEqual([r['agent_id'] for r in result['routing_candidates']],['BOTH'])
        self.assertEqual(result['roster_exclusions']['invalid_roster_fields'],2)
        self.con.execute("UPDATE raw.agents SET current_case_load='10'")
        self.assertFalse(recommend(self.con,value,self.when)['routing_candidates'])

    def test_non_open_stale_hold_and_unknown_language_block_proposals(self):
        self.history()
        for status in ('cured','closed',None):
            value=bundle();value['case']['case_status']=status
            result=recommend(self.con,value,self.when)
            self.assertEqual(result['action_code'],'non_open_review')
            self.assertTrue(result['payment_request_paused']);self.assertIsNone(result['suggested_channel']);self.assertFalse(result['routing_candidates'])
        value=bundle();value['features']['action_eligibility']='hold_insolvency'
        result=recommend(self.con,value,self.when);self.assertFalse(result['routing_candidates']);self.assertIsNone(result['suggested_channel'])
        value=bundle();value['controls']['preferred_language']=None
        self.assertEqual(recommend(self.con,value,self.when)['action_code'],'language_review')
        self.assertFalse(recommend(self.con,bundle(),self.when.replace(day=29))['routing_candidates'])


if __name__=='__main__':unittest.main()
