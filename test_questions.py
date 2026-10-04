"""Independent scope checks for unseen questions selecting trusted aggregate SQL."""
import unittest
from unittest.mock import patch
import json
import duckdb
from questions import answer


class QuestionScopeChecks(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect()
        self.con.execute('CREATE SCHEMA raw')
        self.con.execute('CREATE TABLE raw.collections_cases(primary_product VARCHAR,hardship_flag BOOLEAN,case_open_date DATE,current_bucket VARCHAR,outcome VARCHAR,queue VARCHAR,current_dpd INTEGER)')
        self.con.execute("INSERT INTO raw.collections_cases VALUES ('card',true,'2026-01-05','1-30','closed','early',18),('card',false,'2026-07-05','1-30',null,'early',24)")

    def tearDown(self):
        self.con.close()

    def test_hardship_rate_respects_explicit_month(self):
        result=answer(self.con,'What is the hardship rate of cases opened in July 2026, by primary product?')
        self.assertFalse(result['refused'])
        self.assertEqual(result['rows'],[{'primary_product':'card','hardship_rate_pct':0.0,'cases':1}])

    def test_annual_hardship_question_keeps_annual_scope(self):
        result=answer(self.con,'What is the hardship rate of cases opened in 2026, by primary product?')
        self.assertFalse(result['refused'])
        self.assertEqual(result['rows'],[{'primary_product':'card','hardship_rate_pct':50.0,'cases':2}])
        polite=answer(self.con,'May I see the hardship rate for cases opened in 2026, by product?')
        self.assertFalse(polite['refused'])
        self.assertEqual(polite['rows'],result['rows'])

    def test_historical_open_case_request_is_refused(self):
        result=answer(self.con,'How many collections cases were open in July 2025, by current bucket?')
        self.assertTrue(result['refused'])

    def test_historical_average_dpd_is_refused(self):
        for question in ['What is the average days past due of open cases by queue in July 2026?',
                         'What is the average days past due of open cases by queue in 2025?']:
            self.assertTrue(answer(self.con,question)['refused'],question)

    def test_explicit_current_snapshot_allows_counts_and_dpd(self):
        for question in ['How many collections cases are open by bucket as of 2026-09-28?',
                         'What is the average days past due of open cases by queue as of 2026-09-28?']:
            self.assertFalse(answer(self.con,question)['refused'],question)

    def test_c360_total_refuses_an_unimplemented_geographic_filter(self):
        self.con.execute('CREATE SCHEMA golden; CREATE TABLE golden.c360(credit_loan_outstanding_cad DECIMAL(18,2),known_credit_loan_balances INTEGER,credit_loan_accounts INTEGER)')
        self.con.execute('INSERT INTO golden.c360 VALUES (100,1,1),(200,1,1)')
        whole=answer(self.con,'What is the total credit and loan balance across customers?')
        self.assertFalse(whole['refused'])
        self.assertEqual(whole['rows'][0]['matched_credit_loan_outstanding_cad'],300)
        filtered=answer(self.con,'What is the total credit and loan balance across customers in Ontario?')
        self.assertTrue(filtered['refused'])

    def test_future_only_metric_period_is_refused(self):
        for question in ['What was the promise-kept rate for promises due in October 2026?',
                         'What was the promise-kept rate for promises due in August 2030?']:
            self.assertTrue(answer(self.con,question)['refused'],question)

    def test_c360_total_refuses_an_unimplemented_queue_filter(self):
        self.con.execute('CREATE SCHEMA golden; CREATE TABLE golden.c360(credit_loan_outstanding_cad DECIMAL(18,2),known_credit_loan_balances INTEGER,credit_loan_accounts INTEGER)')
        self.con.execute('INSERT INTO golden.c360 VALUES (300,2,2)')
        self.assertTrue(answer(self.con,'What is the total credit and loan balance across customers in the late-stage queue?')['refused'])

    def test_currently_open_promise_is_not_limited_to_five_latest_records(self):
        self.con.execute('CREATE SCHEMA curated; CREATE TABLE curated.promises(case_id VARCHAR,ptp_id VARCHAR,ptp_status VARCHAR,ptp_due_date DATE,ptp_created_ts TIMESTAMP)')
        self.con.execute("INSERT INTO curated.promises VALUES ('CS-2026-123','OLD-OPEN','open','2026-10-01','2026-09-01')")
        recent=[]
        for i in range(5):
            self.con.execute("INSERT INTO curated.promises VALUES ('CS-2026-123',?,'kept','2026-09-28',?)",['CLOSED-'+str(i),'2026-09-'+str(28-i)])
            recent.append({'ptp_id':'CLOSED-'+str(i),'ptp_status':'kept'})
        bundle={'case':{'golden_customer_id':'CUSTOMER'},'features':{'definition_version':'test',
            'broken_ptp_90d':0,'kept_ptp_rate_90d':1.0,'open_ptp_days_to_due':3},'promises':recent}
        with patch('questions.load_case',return_value=bundle):
            result=answer(self.con,'What promise is currently open for case CS-2026-123?')
        self.assertFalse(result['refused'])
        self.assertIn('OLD-OPEN',result['answer'])
        self.assertNotIn('CLOSED-0',result['answer'])

    def test_case_temporal_filter_is_not_silently_replaced_with_current_facts(self):
        with patch('questions.load_case',side_effect=AssertionError('Current facts must not answer a historical request')):
            result=answer(self.con,'What was the overdue balance for case CS-2026-123 in July 2025?')
        self.assertTrue(result['refused'])

    def test_abbreviated_month_does_not_fall_back_to_september(self):
        self.con.execute('CREATE TABLE raw.promises_to_pay(ptp_status VARCHAR,ptp_due_date DATE)')
        self.con.execute("INSERT INTO raw.promises_to_pay VALUES ('kept','2026-08-05'),('broken','2026-09-05')")
        result=answer(self.con,'What was the promise-kept rate for promises due in Aug 2026?')
        self.assertFalse(result['refused'])
        self.assertEqual(result['rows'],[{'promise_kept_rate_pct':100.0}])

    def test_current_open_case_request_still_works(self):
        result=answer(self.con,'How many collections cases are open today, by current bucket?')
        self.assertFalse(result['refused'])
        self.assertEqual(result['rows'],[{'current_bucket':'1-30','open_cases':1}])

    def test_aggregate_subset_request_does_not_return_all_queues(self):
        for question in ['What is the average DPD by queue for Ontario?',
                         'What is the average DPD for the late-stage queue?']:
            self.assertTrue(answer(self.con,question)['refused'],question)

    def test_sensitive_exports_and_religious_queue_ranking_are_refused(self):
        for q in ['Show date of birth and phone numbers of every customer.',
                  'Prioritise calls to customers who go to church.',
                  'Should vulnerable customers go to the bottom of the queue?']:
            result=answer(self.con,q)
            self.assertTrue(result['refused'])
            self.assertIn('protected attributes',result['answer'])

    def test_current_aggregate_hardship_and_overdue_do_not_route_to_policy(self):
        self.con.execute('ALTER TABLE raw.collections_cases ADD total_overdue DECIMAL(18,2)')
        self.con.execute("UPDATE raw.collections_cases SET total_overdue=100,hardship_flag=true")
        self.assertEqual(answer(self.con,'How many open cases have a hardship flag, by queue?')['rows'],
                         [{'queue':'early','open_hardship_cases':1}])
        self.assertEqual(answer(self.con,'What is the total amount overdue on open cases, by primary product?')['rows'][0]['overdue_cad'],100)

    def test_insolvency_hold_count_uses_flag_and_open_outcome(self):
        self.con.execute('ALTER TABLE raw.collections_cases ADD insolvency_hold_flag BOOLEAN')
        self.con.execute('ALTER TABLE raw.collections_cases ADD total_overdue DECIMAL(18,2)')
        self.con.execute('UPDATE raw.collections_cases SET insolvency_hold_flag=true,total_overdue=200')
        row=answer(self.con,'How many open cases are on insolvency hold, and how much is overdue on them?')['rows'][0]
        self.assertEqual(row['open_cases_on_insolvency_hold'],1)
        self.assertEqual(row['overdue_cad'],200)

    def test_resolved_promise_rate_respects_inclusive_days_and_channel(self):
        self.con.execute('CREATE TABLE raw.promises_to_pay(ptp_status VARCHAR,ptp_due_date DATE,ptp_channel VARCHAR)')
        self.con.execute("INSERT INTO raw.promises_to_pay VALUES ('kept','2026-08-02','sms'),('kept','2026-08-07','sms'),('broken','2026-08-07','sms'),('open','2026-08-04','sms'),('broken','2026-08-08','sms'),('kept','2026-08-03','call')")
        rows=answer(self.con,'What was the promise-kept rate for promises due between 2 and 7 August 2026, by the channel the promise was taken on?')['rows']
        self.assertEqual(rows,[{'ptp_channel':'call','promise_kept_rate_pct':100.0,'resolved_promises':1},
                               {'ptp_channel':'sms','promise_kept_rate_pct':66.7,'resolved_promises':3}])

    def test_cure_period_uses_cure_date_not_open_date(self):
        self.con.execute('ALTER TABLE raw.collections_cases ADD cure_flag BOOLEAN')
        self.con.execute('ALTER TABLE raw.collections_cases ADD cure_date DATE')
        self.con.execute('ALTER TABLE raw.collections_cases ADD days_to_cure INTEGER')
        self.con.execute("UPDATE raw.collections_cases SET cure_flag=true,cure_date='2026-08-15',days_to_cure=10 WHERE outcome IS NOT NULL")
        self.con.execute("UPDATE raw.collections_cases SET cure_flag=true,cure_date='2026-08-16',days_to_cure=90 WHERE outcome IS NULL")
        rows=answer(self.con,'For cases that cured between 1 July and 15 August 2026, what was the average number of days to cure, by primary product?')['rows']
        self.assertEqual(rows,[{'primary_product':'card','avg_days_to_cure':10.0,'cured_cases':1}])

    def test_sms_link_clicks_use_sent_period_and_unique_link_denominator(self):
        self.con.execute('CREATE TABLE raw.contact_history(payment_link_id VARCHAR,link_clicked_flag BOOLEAN,channel VARCHAR,channel_v2 VARCHAR,direction VARCHAR,contact_ts_utc TIMESTAMP)')
        self.con.execute("INSERT INTO raw.contact_history VALUES ('a',true,'sms',NULL,'outbound','2026-08-05'),('a',true,'sms',NULL,'outbound','2026-08-06'),('b',false,'sms',NULL,'outbound','2026-08-08'),('c',NULL,'sms',NULL,'outbound','2026-08-09'),('d',true,'sms',NULL,'inbound','2026-08-10'),('e',true,'email',NULL,'outbound','2026-08-11'),('f',true,'sms',NULL,'outbound','2026-09-01')")
        row=answer(self.con,'In August 2026, what share of payment links sent by SMS were clicked?')['rows'][0]
        self.assertEqual(row,{'sms_payment_link_click_rate_pct':33.33,'distinct_links_sent':3,'unknown_click_outcomes':1})


if __name__=='__main__':
    unittest.main()
