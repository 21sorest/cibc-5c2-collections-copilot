-- Current release only. Cases are current facts, so historical cutoffs are rejected by features.py.
CREATE SCHEMA IF NOT EXISTS features;
CREATE OR REPLACE TABLE features.contact_controls AS
SELECT m.golden_customer_id,
 bool_and(try_cast(c.consent_call AS BOOLEAN) IS TRUE) AS consent_call,
 bool_and(try_cast(c.consent_sms AS BOOLEAN) IS TRUE) AS consent_sms,
 bool_and(try_cast(c.consent_email AS BOOLEAN) IS TRUE) AS consent_email,
 bool_or(try_cast(c.internal_do_not_call_flag AS BOOLEAN) IS NOT FALSE) AS do_not_call,
 bool_or(try_cast(c.cease_communication_flag AS BOOLEAN) IS NOT FALSE) AS cease,
 bool_or(try_cast(c.deceased_flag AS BOOLEAN) IS NOT FALSE) AS deceased,
 bool_or(try_cast(c.bankruptcy_flag AS BOOLEAN) IS NOT FALSE OR try_cast(c.consumer_proposal_flag AS BOOLEAN) IS NOT FALSE) AS insolvency,
 bool_or(try_cast(c.credit_counselling_agency_flag AS BOOLEAN) IS NOT FALSE OR try_cast(c.legal_representative_flag AS BOOLEAN) IS NOT FALSE) AS represented,
 bool_and(try_cast(c.sunday_contact_permitted AS BOOLEAN) IS TRUE) AS sunday_permitted,
 CASE WHEN count(DISTINCT c.time_zone)=1 THEN min(c.time_zone) END AS time_zone,
 CASE WHEN count(DISTINCT c.province_code)=1 THEN min(c.province_code) END AS province,
 max(try_cast(c.permitted_call_start_local AS TIME)) AS permitted_start,
 min(try_cast(c.permitted_call_end_local AS TIME)) AS permitted_end,
 max(c.preferred_language) AS preferred_language
FROM raw.customers c JOIN restricted.identity_map m ON m.source_system='crm' AND m.source_key=c.crm_customer_id
WHERE m.status='accepted' GROUP BY 1;

CREATE OR REPLACE TABLE features.case_current AS
WITH accounts AS (
 SELECT l.case_id,max(a.dpd) AS max_dpd,max(a.last_payment_date) AS last_payment
 FROM curated.case_accounts l JOIN curated.accounts a USING(source_system,account_id) GROUP BY 1
), contacts AS (
 SELECT case_id,
 count(*) FILTER(WHERE direction='outbound' AND channel<>'system'
   AND contact_ts_utc>=getvariable('feature_date')-INTERVAL 6 DAY) AS attempts_7d,
 count(*) FILTER(WHERE direction='outbound' AND channel='call'
   AND contact_ts_utc>=getvariable('feature_date')-INTERVAL 6 DAY) AS calls_7d
 FROM curated.contacts WHERE contact_ts_utc<getvariable('feature_date')+INTERVAL 1 DAY GROUP BY 1
), channel_rates AS (
 SELECT case_id,channel,avg(cast(rpc_flag AS INTEGER)) AS rpc_rate
 FROM curated.contacts WHERE direction='outbound' AND channel<>'system'
 AND contact_ts_utc>=getvariable('feature_date')-INTERVAL 89 DAY
 AND contact_ts_utc<getvariable('feature_date')+INTERVAL 1 DAY GROUP BY 1,2
), rates AS (
 SELECT case_id,to_json(map(list(channel ORDER BY channel),list(rpc_rate ORDER BY channel))) AS channel_rates
 FROM channel_rates GROUP BY 1
), promises AS (
 SELECT case_id,
 count(*) FILTER(WHERE ptp_status='broken' AND status_ts>=getvariable('feature_date')-INTERVAL 89 DAY
   AND status_ts<getvariable('feature_date')+INTERVAL 1 DAY) AS broken,
 count(*) FILTER(WHERE ptp_status='kept')::DOUBLE/nullif(count(*) FILTER(WHERE ptp_status IN ('kept','partially_kept','broken')),0) AS kept_rate,
 min(date_diff('day',getvariable('feature_date'),ptp_due_date)) FILTER(WHERE ptp_status='open' AND ptp_due_date>=getvariable('feature_date')) AS days_to_due
 FROM curated.promises WHERE ptp_created_ts<getvariable('feature_date')+INTERVAL 1 DAY
 AND (ptp_status='open' OR (ptp_due_date>=getvariable('feature_date')-INTERVAL 89 DAY
   AND ptp_due_date<=getvariable('feature_date') AND status_ts<getvariable('feature_date')+INTERVAL 1 DAY)) GROUP BY 1
), salary_months AS (
 SELECT a.golden_customer_id,try_cast(s.credit_month||'-01' AS DATE) AS month,
 sum(s.credit_amount_total) AS amount
 FROM raw.salary_credit_history s JOIN curated.accounts a
 ON a.source_system='core_banking' AND a.account_id=s.deposit_account_id
 JOIN restricted.identity_map m ON m.source_system='crm' AND m.source_key=s.crm_customer_id AND m.golden_customer_id=a.golden_customer_id
 WHERE m.status='accepted' AND s.credit_amount_total>=0
 AND try_cast(s.credit_month||'-01' AS DATE)>=date_trunc('month',getvariable('feature_date'))-INTERVAL 4 MONTH
 AND try_cast(s.credit_month||'-01' AS DATE)<date_trunc('month',getvariable('feature_date')) GROUP BY 1,2
), salary AS (
 SELECT golden_customer_id,
 CASE WHEN count(*)=4 AND avg(amount) FILTER(WHERE month<date_trunc('month',getvariable('feature_date'))-INTERVAL 1 MONTH)>0
 THEN 1-max(amount) FILTER(WHERE month=date_trunc('month',getvariable('feature_date'))-INTERVAL 1 MONTH)
 /avg(amount) FILTER(WHERE month<date_trunc('month',getvariable('feature_date'))-INTERVAL 1 MONTH) END AS decline
 FROM salary_months GROUP BY 1
), text_signals AS (
 SELECT case_id,bool_or(hardship) AS hardship,bool_or(callback) AS callback,
 bool_or(cease) AS cease,bool_or(insolvency) AS insolvency,bool_or(dispute) AS dispute,
 to_json(list(struct_pack(source_id:=source_id,kind:=kind,hardship:=hardship,callback:=callback))) AS evidence
 FROM features.text_evidence WHERE event_date>=getvariable('feature_date')-INTERVAL 89 DAY
 AND event_date<=getvariable('feature_date') GROUP BY 1
)
SELECT c.case_id,c.golden_customer_id,getvariable('feature_date') AS as_of_date,'features-v0.5' AS definition_version,
 greatest(c.current_dpd,a.max_dpd) AS case_max_dpd,c.total_overdue_cad AS case_overdue_cad,
 date_diff('day',a.last_payment,getvariable('feature_date')) AS days_since_payment,
 coalesce(p.broken,0) AS broken_ptp_90d,p.kept_rate AS kept_ptp_rate_90d,p.days_to_due AS open_ptp_days_to_due,
 s.decline AS salary_decline_ratio,coalesce(t.attempts_7d,0) AS contact_attempts_7d,
 coalesce(r.channel_rates,'{}') AS channel_rpc_rate_90d,
 x.hardship AS hardship_mention,x.callback AS callback_request,
 CASE WHEN c.cease_contact_flag IS NOT FALSE OR q.cease IS NOT FALSE OR x.cease IS TRUE THEN 'hold_cease'
 WHEN c.insolvency_hold_flag IS NOT FALSE OR q.insolvency IS NOT FALSE OR x.insolvency IS TRUE THEN 'hold_insolvency'
 WHEN c.deceased_hold_flag IS NOT FALSE OR q.deceased IS NOT FALSE THEN 'hold_deceased'
 WHEN q.represented IS NOT FALSE THEN 'representative_review'
 WHEN c.dispute_flag IS NOT FALSE OR x.dispute IS TRUE THEN 'dispute_review'
 WHEN coalesce(t.calls_7d,0)>=least(coalesce(c.contact_cap_7d,0),3) THEN 'call_cap_reached'
 ELSE 'requires_live_policy_check' END AS action_eligibility,
 coalesce(t.calls_7d,0) AS outbound_calls_7d,c.account_link_state AS account_coverage,
 coalesce(x.evidence,'[]') AS text_sources
FROM curated.cases c LEFT JOIN accounts a USING(case_id) LEFT JOIN contacts t USING(case_id)
LEFT JOIN promises p USING(case_id) LEFT JOIN rates r USING(case_id) LEFT JOIN text_signals x USING(case_id)
LEFT JOIN salary s USING(golden_customer_id) LEFT JOIN features.contact_controls q USING(golden_customer_id);
CREATE INDEX IF NOT EXISTS feature_case_lookup ON features.case_current(case_id);

