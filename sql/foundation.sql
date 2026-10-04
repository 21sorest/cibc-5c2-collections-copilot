-- Matching data stays in restricted. Approved outputs contain explicit columns.
CREATE OR REPLACE MACRO norm_name(s) AS nullif(array_to_string(list_sort(list_filter(
 regexp_split_to_array(regexp_replace(replace(replace(replace(lower(strip_accents(s)),'-',''),chr(39),''),chr(8217),''),'[^a-z]+',' ','g'),' '),
 token -> token<>'')), ' '),'');
CREATE OR REPLACE MACRO name_initials(s) AS array_to_string(list_transform(string_split(norm_name(s),' '),token -> left(token,1)),' ');
CREATE OR REPLACE MACRO compatible_name(source,first,middle,last) AS coalesce(
 norm_name(first) IS NOT NULL AND norm_name(last) IS NOT NULL AND norm_name(source) IN (
 norm_name(first||' '||last),norm_name(first||' '||coalesce(middle,'')||' '||last),
 norm_name(name_initials(first)||' '||last),norm_name(name_initials(first||' '||coalesce(middle,''))||' '||last)),false);
CREATE OR REPLACE MACRO phone_digits(s) AS regexp_replace(s,'[^0-9]','','g');
CREATE OR REPLACE MACRO norm_phone(s) AS CASE WHEN regexp_matches(s,'[a-zA-Z]') THEN NULL
 WHEN len(phone_digits(s))=10 THEN phone_digits(s)
 WHEN len(phone_digits(s))=11 AND starts_with(phone_digits(s),'1') THEN substr(phone_digits(s),2) END;
CREATE OR REPLACE MACRO dob_candidates(s) AS list_sort(list_distinct([
 cast(try_strptime(trim(s),'%Y-%m-%d') AS DATE),cast(try_strptime(trim(s),'%Y/%m/%d') AS DATE),
 cast(try_strptime(trim(s),'%Y%m%d') AS DATE),cast(try_strptime(trim(s),'%d-%m-%Y') AS DATE),
 cast(try_strptime(trim(s),'%m-%d-%Y') AS DATE),cast(try_strptime(trim(s),'%d/%m/%Y') AS DATE),
 cast(try_strptime(trim(s),'%m/%d/%Y') AS DATE),cast(try_strptime(trim(s),'%b %d %Y') AS DATE),
 cast(try_strptime(trim(s),'%B %d %Y') AS DATE)]));
CREATE OR REPLACE MACRO one_date(s) AS CASE WHEN len(dob_candidates(s))=1 THEN dob_candidates(s)[1] END;
CREATE TABLE restricted.quality_counts(source VARCHAR, issue VARCHAR, affected_records BIGINT);

CREATE TABLE restricted.customer_records AS
WITH selected AS (
 SELECT crm_customer_id, duplicate_of_crm_id, first_name, middle_name, last_name,
        norm_name(first_name || ' ' || last_name) AS name_key,
        one_date(date_of_birth) AS dob,
        norm_phone(coalesce(primary_phone_e164,primary_phone_raw)) AS phone,
        try_cast(is_deleted AS BOOLEAN) AS is_deleted,
        record_hash, 'data/customers.csv' AS source_file
 FROM raw.customers
)
SELECT *, hash(selected) AS payload_hash FROM selected;

CREATE TABLE restricted.crm_conflicts AS
SELECT crm_customer_id FROM restricted.customer_records
GROUP BY 1 HAVING count(DISTINCT payload_hash)>1;

CREATE TABLE restricted.crm_profiles AS
SELECT c.* FROM restricted.customer_records c
WHERE crm_customer_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM restricted.crm_conflicts x WHERE x.crm_customer_id=c.crm_customer_id)
QUALIFY row_number() OVER (PARTITION BY crm_customer_id ORDER BY payload_hash)=1;

CREATE TABLE restricted.crm_base_identity AS
SELECT 'crm'::VARCHAR AS source_system, c.crm_customer_id::VARCHAR AS source_key,
 CASE WHEN c.is_deleted IS NOT FALSE THEN NULL
      WHEN c.duplicate_of_crm_id IS NULL THEN 'C360:'||c.crm_customer_id
      WHEN p.crm_customer_id IS NOT NULL AND p.is_deleted IS FALSE
       AND p.duplicate_of_crm_id IS NULL AND c.dob=p.dob AND c.name_key=p.name_key
      THEN 'C360:'||p.crm_customer_id END::VARCHAR AS golden_customer_id,
 CASE WHEN c.duplicate_of_crm_id IS NULL THEN 'native_crm_key' ELSE 'validated_duplicate_pointer' END::VARCHAR AS match_method,
 'high'::VARCHAR AS match_confidence,
 CASE WHEN c.is_deleted IS NOT FALSE THEN 'quarantined'
      WHEN c.duplicate_of_crm_id IS NULL THEN 'accepted'
      WHEN p.crm_customer_id IS NOT NULL AND p.is_deleted IS FALSE
       AND p.duplicate_of_crm_id IS NULL AND c.dob=p.dob AND c.name_key=p.name_key THEN 'accepted'
      ELSE 'quarantined' END::VARCHAR AS status,
 CASE WHEN c.is_deleted IS NOT FALSE THEN 'deleted_or_unknown_delete_state'
      WHEN c.duplicate_of_crm_id IS NOT NULL AND NOT coalesce(
       p.crm_customer_id IS NOT NULL AND p.is_deleted IS FALSE AND p.duplicate_of_crm_id IS NULL
       AND c.dob=p.dob AND c.name_key=p.name_key,false) THEN 'unvalidated_duplicate_pointer'
      ELSE NULL END::VARCHAR AS reason,
 1::BIGINT AS candidate_count
FROM restricted.crm_profiles c LEFT JOIN restricted.crm_profiles p ON c.duplicate_of_crm_id=p.crm_customer_id;

CREATE TABLE restricted.crm_identity AS
SELECT * FROM restricted.crm_base_identity
UNION ALL
SELECT 'crm',crm_customer_id,NULL,'conflicting_crm_records','unknown','quarantined','conflicting_payload',0
FROM restricted.crm_conflicts WHERE crm_customer_id IS NOT NULL;

-- ponytail: one-hop duplicate pointers only; chains require steward review.
CREATE TABLE restricted.account_inputs AS
WITH selected AS (
 SELECT 'cards' AS source_system, card_account_id AS account_id, src_customer_ref AS source_key,
        cardholder_name_raw AS source_name, dob_candidates(cardholder_dob_raw) AS dob_options,
        norm_phone(cardholder_phone_raw) AS phone, one_date(snapshot_date) AS snapshot_date,
        try_cast(current_balance AS DECIMAL(18,2)) AS balance_cad,
        try_cast(past_due_amount AS DECIMAL(18,2)) AS past_due_cad,
        try_cast(dpd AS INTEGER) AS dpd, 'CAD' AS currency,
        last_payment_date AS last_payment_raw, one_date(last_payment_date) AS last_payment_date,
        current_balance IS NOT NULL AS balance_supplied, past_due_amount IS NOT NULL AS overdue_supplied,
        account_status, record_hash, 'data/card_accounts.csv' AS source_file
 FROM raw.card_accounts
 UNION ALL
 SELECT 'lending',loan_id,src_customer_ref,borrower_name_raw,dob_candidates(borrower_dob_raw),
        norm_phone(borrower_phone_raw),one_date(snapshot_date),
        try_cast(total_outstanding AS DECIMAL(18,2)),try_cast(past_due_amount AS DECIMAL(18,2)),
        try_cast(dpd AS INTEGER),'CAD',last_payment_date,one_date(last_payment_date),
        total_outstanding IS NOT NULL,past_due_amount IS NOT NULL,NULL,record_hash,'data/loan_accounts.csv'
 FROM raw.loan_accounts
 UNION ALL
 SELECT 'core_banking',deposit_account_id,src_customer_ref,holder_name_raw,dob_candidates(holder_dob_raw),
        norm_phone(holder_phone_raw),one_date(snapshot_date),
        CASE WHEN currency='CAD' THEN try_cast(current_balance AS DECIMAL(18,2)) END,
        NULL,try_cast(overdraft_dpd AS INTEGER),currency,NULL,NULL,
        currency='CAD' AND current_balance IS NOT NULL,false,account_status,record_hash,'data/deposit_accounts.csv'
 FROM raw.deposit_accounts
)
SELECT *,hash(selected) AS payload_hash FROM selected;

CREATE TABLE restricted.account_latest AS
SELECT * FROM restricted.account_inputs a
WHERE snapshot_date<=getvariable('snapshot_date')
QUALIFY snapshot_date=max(snapshot_date) OVER (PARTITION BY source_system,account_id);

CREATE TABLE restricted.account_conflicts AS
SELECT source_system,account_id FROM restricted.account_latest GROUP BY ALL
HAVING count(DISTINCT payload_hash)>1;

CREATE TABLE restricted.account_records AS
SELECT a.*,
 CASE WHEN account_id IS NULL OR source_key IS NULL THEN 'missing_key'
      WHEN x.account_id IS NOT NULL THEN 'conflicting_payload'
      WHEN (balance_supplied AND balance_cad IS NULL) OR (overdue_supplied AND past_due_cad IS NULL)
        OR past_due_cad<0 OR dpd<0 OR (dpd IS NULL AND source_system<>'core_banking') THEN 'invalid_money_or_dpd'
      WHEN last_payment_raw IS NOT NULL AND last_payment_date IS NULL THEN 'invalid_payment_date'
      WHEN last_payment_date>getvariable('snapshot_date') THEN 'future_payment_date'
      ELSE NULL END AS quality_reason
FROM restricted.account_latest a LEFT JOIN restricted.account_conflicts x USING(source_system,account_id)
QUALIFY row_number() OVER (PARTITION BY source_system,account_id ORDER BY payload_hash)=1;

CREATE TABLE restricted.product_profiles AS
SELECT DISTINCT source_system,source_key,source_name,dob_options,phone
FROM restricted.account_latest WHERE source_key IS NOT NULL;

CREATE TABLE restricted.product_candidates AS
WITH expanded AS (
 SELECT *,unnest(dob_options) AS candidate_dob FROM restricted.product_profiles WHERE phone IS NOT NULL
)
SELECT DISTINCT p.* EXCLUDE(candidate_dob),m.golden_customer_id,
 CASE WHEN norm_name(p.source_name)=c.name_key THEN 'high' ELSE 'medium' END AS confidence
FROM expanded p
JOIN restricted.crm_profiles c ON p.phone=c.phone AND p.candidate_dob=c.dob
JOIN restricted.crm_identity m ON m.source_key=c.crm_customer_id AND m.status='accepted'
WHERE p.phone IS NOT NULL AND compatible_name(p.source_name,c.first_name,c.middle_name,c.last_name);

CREATE TABLE restricted.product_matches AS
SELECT p.source_system,p.source_key,count(DISTINCT c.golden_customer_id) AS candidate_count,
       min(c.golden_customer_id) AS candidate_id,
       CASE WHEN bool_and(c.confidence='high') THEN 'high' ELSE 'medium' END AS confidence,
       count(DISTINCT p.phone)>1
        OR count(DISTINCT CASE WHEN len(p.dob_options)=1 THEN p.dob_options[1] END)>1 AS conflicting_anchors
FROM restricted.product_profiles p
LEFT JOIN restricted.product_candidates c USING(source_system,source_key,source_name,dob_options,phone)
GROUP BY 1,2;

-- Validate every available profile against the unique candidate before propagating a source key.
CREATE TABLE restricted.product_inconsistency AS
SELECT DISTINCT p.source_system,p.source_key
FROM restricted.product_profiles p
JOIN restricted.product_matches x USING(source_system,source_key)
JOIN restricted.crm_identity m ON m.golden_customer_id=x.candidate_id
 AND m.match_method='native_crm_key' AND m.status='accepted'
JOIN restricted.crm_profiles c ON c.crm_customer_id=m.source_key
WHERE x.candidate_count=1 AND (
 (p.phone IS NOT NULL AND p.phone IS DISTINCT FROM c.phone)
 OR (len(p.dob_options)>0 AND NOT list_contains(p.dob_options,c.dob))
 OR (p.source_name IS NOT NULL AND NOT compatible_name(p.source_name,c.first_name,c.middle_name,c.last_name)));

CREATE TABLE restricted.product_identity AS
SELECT x.source_system,x.source_key,
 CASE WHEN x.candidate_count=1 AND NOT x.conflicting_anchors AND i.source_key IS NULL THEN x.candidate_id END AS golden_customer_id,
 'unique_dob_phone_consistent_name' AS match_method,
 CASE WHEN x.candidate_count=1 AND NOT x.conflicting_anchors AND i.source_key IS NULL THEN x.confidence ELSE 'unknown' END AS match_confidence,
 CASE WHEN x.candidate_count=1 AND NOT x.conflicting_anchors AND i.source_key IS NULL THEN 'accepted' ELSE 'quarantined' END AS status,
 CASE WHEN x.conflicting_anchors OR i.source_key IS NOT NULL THEN 'conflicting_identity_evidence'
      WHEN x.candidate_count=0 THEN 'insufficient_or_unmatched_evidence'
      WHEN x.candidate_count>1 THEN 'multiple_candidates' END AS reason,
 x.candidate_count
FROM restricted.product_matches x LEFT JOIN restricted.product_inconsistency i USING(source_system,source_key);

CREATE TABLE curated.accounts AS
SELECT a.source_system,a.account_id,a.source_key,m.golden_customer_id,m.match_method,m.match_confidence,
       a.snapshot_date,a.balance_cad,a.past_due_cad,a.dpd,a.currency,a.last_payment_date,a.account_status,a.source_file
FROM restricted.account_records a JOIN restricted.product_identity m USING(source_system,source_key)
WHERE a.quality_reason IS NULL AND m.status='accepted';

-- Interaction account IDs have no source-system field. Reject a resolved contradiction;
-- an unresolved account remains unknown coverage rather than an invented ownership match.
CREATE OR REPLACE MACRO contradicts_account_owner(account_ref, customer_id) AS EXISTS (
 SELECT 1 FROM curated.accounts owner
 WHERE owner.account_id=account_ref AND owner.golden_customer_id IS DISTINCT FROM customer_id);

CREATE TABLE restricted.case_inputs AS
WITH selected AS (
 SELECT case_id,coll_customer_ref AS source_key,one_date(case_open_date) AS case_open_date,
        case_status,primary_account_id,primary_product,account_ids,current_bucket,queue,assigned_agent_id,
        try_cast(current_dpd AS INTEGER) AS current_dpd,
        try_cast(total_overdue AS DECIMAL(18,2)) AS total_overdue_cad,
        current_ptp_id,try_cast(hardship_flag AS BOOLEAN) AS hardship_flag,
        try_cast(cease_contact_flag AS BOOLEAN) AS cease_contact_flag,
        try_cast(insolvency_hold_flag AS BOOLEAN) AS insolvency_hold_flag,
        try_cast(deceased_hold_flag AS BOOLEAN) AS deceased_hold_flag,
        try_cast(dispute_flag AS BOOLEAN) AS dispute_flag,
        try_cast(contact_cap_7d AS INTEGER) AS contact_cap_7d,
        record_hash,'data/collections_cases.csv' AS source_file
 FROM raw.collections_cases
)
SELECT *,hash(selected) AS payload_hash FROM selected;

CREATE TABLE restricted.case_conflicts AS
SELECT case_id FROM restricted.case_inputs GROUP BY 1 HAVING count(DISTINCT payload_hash)>1;

CREATE TABLE restricted.case_records AS
SELECT c.*,m.golden_customer_id,
 CASE WHEN c.case_id IS NULL OR c.source_key IS NULL THEN 'missing_key'
      WHEN x.case_id IS NOT NULL THEN 'conflicting_payload'
      WHEN m.status IS DISTINCT FROM 'accepted' THEN 'unresolved_customer'
      WHEN case_open_date IS NULL OR case_open_date>getvariable('snapshot_date') THEN 'invalid_or_future_open_date'
      WHEN current_dpd IS NULL OR current_dpd<0 OR total_overdue_cad IS NULL OR total_overdue_cad<0 THEN 'invalid_money_or_dpd'
      WHEN try_cast(account_ids AS VARCHAR[]) IS NULL THEN 'invalid_account_list'
      ELSE NULL END AS quality_reason
FROM restricted.case_inputs c LEFT JOIN restricted.case_conflicts x USING(case_id)
LEFT JOIN restricted.crm_identity m ON m.source_key=c.source_key
QUALIFY row_number() OVER (PARTITION BY case_id ORDER BY payload_hash)=1;

CREATE TABLE restricted.collections_identity AS
SELECT 'collections' AS source_system,source_key,
 CASE WHEN count(DISTINCT golden_customer_id)=1 THEN min(golden_customer_id) END AS golden_customer_id,
 'validated_crm_reference' AS match_method,CASE WHEN count(DISTINCT golden_customer_id)=1 THEN 'high' ELSE 'unknown' END AS match_confidence,
 CASE WHEN count(DISTINCT golden_customer_id)=1 THEN 'accepted' ELSE 'quarantined' END AS status,
 CASE WHEN count(DISTINCT golden_customer_id)<>1 THEN 'unresolved_customer' END AS reason,
 count(DISTINCT golden_customer_id) AS candidate_count
FROM restricted.case_records WHERE source_key IS NOT NULL GROUP BY source_key;

CREATE TABLE restricted.identity_map AS
SELECT * FROM restricted.crm_identity
UNION ALL SELECT * FROM restricted.product_identity
UNION ALL SELECT * FROM restricted.collections_identity;

CREATE TABLE restricted.case_account_links AS
WITH requested AS (
 SELECT case_id,golden_customer_id,unnest(try_cast(account_ids AS VARCHAR[])) AS account_id
 FROM restricted.case_records WHERE quality_reason IS NULL
)
SELECT r.case_id,r.account_id,a.source_system,
 CASE WHEN count(a.account_id) OVER (PARTITION BY r.case_id,r.account_id)>1 THEN 'ambiguous_account_id'
      WHEN a.account_id IS NULL THEN 'missing_or_quarantined_account'
      WHEN r.golden_customer_id IS DISTINCT FROM a.golden_customer_id THEN 'customer_mismatch'
      ELSE NULL END AS quality_reason
FROM (SELECT DISTINCT * FROM requested) r LEFT JOIN curated.accounts a USING(account_id);

CREATE TABLE curated.cases AS
SELECT c.case_id,c.golden_customer_id,c.case_open_date,c.case_status,c.primary_account_id,c.primary_product,
       c.current_dpd,c.total_overdue_cad,c.current_bucket,c.queue,c.assigned_agent_id,c.current_ptp_id,
       c.hardship_flag,c.cease_contact_flag,c.insolvency_hold_flag,c.deceased_hold_flag,c.dispute_flag,c.contact_cap_7d,
       CASE WHEN EXISTS(SELECT 1 FROM restricted.case_account_links l WHERE l.case_id=c.case_id AND l.quality_reason IS NOT NULL)
            THEN 'partial' ELSE 'complete' END AS account_link_state,c.source_file
FROM restricted.case_records c WHERE quality_reason IS NULL;

CREATE TABLE curated.case_accounts AS
SELECT case_id,source_system,account_id FROM restricted.case_account_links WHERE quality_reason IS NULL;

CREATE TABLE restricted.contact_inputs AS
WITH selected AS (
 SELECT contact_id,case_id,crm_customer_id,account_id,direction,
        coalesce(channel_v2,channel) AS channel,
        channel IS NOT NULL AND channel_v2 IS NOT NULL AND channel<>channel_v2 AS channel_conflict,
        try_cast(contact_ts_utc AS TIMESTAMP) AS contact_ts_utc,
        try_cast(rpc_flag AS BOOLEAN) AS rpc_flag,outcome_code,
        try_cast(contact_cost_cad AS DECIMAL(18,2)) AS contact_cost_cad,
        record_hash,'data/contact_history.csv' AS source_file
 FROM raw.contact_history
)
SELECT *,hash(selected) AS payload_hash FROM selected;

CREATE TABLE restricted.promise_inputs AS
WITH selected AS (
 SELECT ptp_id,case_id,crm_customer_id,account_id,ptp_status,
        try_cast(ptp_created_ts AS TIMESTAMP) AS ptp_created_ts,
        one_date(ptp_due_date) AS ptp_due_date,try_cast(status_ts AS TIMESTAMP) AS status_ts,
        status_ts AS status_ts_raw,
        try_cast(ptp_amount AS DECIMAL(18,2)) AS ptp_amount_cad,
        try_cast(amount_paid_against AS DECIMAL(18,2)) AS amount_paid_cad,
        'data/promises_to_pay.csv' AS source_file
 FROM raw.promises_to_pay
)
SELECT *,hash(selected) AS payload_hash FROM selected;

CREATE TABLE restricted.note_inputs AS
WITH selected AS (
 SELECT note_id,case_id,crm_customer_id,account_id,
        try_cast(note_ts_utc AS TIMESTAMP) AS note_ts_utc,note_text,
        'data/agent_notes.csv' AS source_file
 FROM raw.agent_notes
)
SELECT *,hash(selected) AS payload_hash FROM selected;

CREATE TABLE restricted.interaction_conflicts AS
SELECT 'contacts' AS source,contact_id AS record_id FROM restricted.contact_inputs GROUP BY 2 HAVING count(DISTINCT payload_hash)>1
UNION ALL
SELECT 'promises',ptp_id FROM restricted.promise_inputs GROUP BY 2 HAVING count(DISTINCT payload_hash)>1
UNION ALL
SELECT 'notes',note_id FROM restricted.note_inputs GROUP BY 2 HAVING count(DISTINCT payload_hash)>1;

CREATE TABLE restricted.contact_records AS
SELECT t.*,c.golden_customer_id,
 CASE WHEN contact_id IS NULL THEN 'missing_key'
      WHEN x.record_id IS NOT NULL THEN 'conflicting_payload'
      WHEN c.case_id IS NULL THEN 'unresolved_case'
      WHEN m.golden_customer_id IS DISTINCT FROM c.golden_customer_id THEN 'customer_reference_mismatch'
      WHEN contradicts_account_owner(t.account_id,c.golden_customer_id) THEN 'account_customer_mismatch'
      WHEN contact_ts_utc IS NULL OR cast(contact_ts_utc AS DATE)>getvariable('snapshot_date') THEN 'invalid_or_future_timestamp'
      WHEN channel_conflict THEN 'channel_conflict'
      WHEN channel IS NULL THEN 'missing_channel'
      WHEN contact_cost_cad IS NULL OR contact_cost_cad<0 THEN 'invalid_contact_cost'
      ELSE NULL END AS quality_reason
FROM restricted.contact_inputs t LEFT JOIN curated.cases c USING(case_id)
LEFT JOIN restricted.identity_map m ON m.source_system='crm' AND m.source_key=t.crm_customer_id
LEFT JOIN restricted.interaction_conflicts x ON x.source='contacts' AND x.record_id=t.contact_id
QUALIFY row_number() OVER (PARTITION BY contact_id ORDER BY payload_hash)=1;

CREATE TABLE restricted.promise_records AS
SELECT t.*,c.golden_customer_id,
 CASE WHEN ptp_id IS NULL THEN 'missing_key'
      WHEN x.record_id IS NOT NULL THEN 'conflicting_payload'
      WHEN c.case_id IS NULL THEN 'unresolved_case'
      WHEN m.golden_customer_id IS DISTINCT FROM c.golden_customer_id THEN 'customer_reference_mismatch'
      WHEN contradicts_account_owner(t.account_id,c.golden_customer_id) THEN 'account_customer_mismatch'
      WHEN ptp_due_date IS NULL OR ptp_created_ts IS NULL OR cast(ptp_created_ts AS DATE)>getvariable('snapshot_date') THEN 'invalid_or_future_creation_date'
      WHEN status_ts_raw IS NOT NULL AND status_ts IS NULL THEN 'invalid_status_timestamp'
      WHEN status_ts<ptp_created_ts OR cast(status_ts AS DATE)>getvariable('snapshot_date') THEN 'invalid_or_future_status_timestamp'
      WHEN ptp_amount_cad IS NULL OR ptp_amount_cad<0 OR amount_paid_cad<0 THEN 'invalid_money'
      WHEN ptp_status NOT IN ('open','kept','partially_kept','broken','cancelled') OR ptp_status IS NULL THEN 'invalid_status'
      ELSE NULL END AS quality_reason
FROM restricted.promise_inputs t LEFT JOIN curated.cases c USING(case_id)
LEFT JOIN restricted.identity_map m ON m.source_system='crm' AND m.source_key=t.crm_customer_id
LEFT JOIN restricted.interaction_conflicts x ON x.source='promises' AND x.record_id=t.ptp_id
QUALIFY row_number() OVER (PARTITION BY ptp_id ORDER BY payload_hash)=1;

CREATE TABLE restricted.note_records AS
SELECT t.*,c.golden_customer_id,
 CASE WHEN note_id IS NULL THEN 'missing_key'
      WHEN x.record_id IS NOT NULL THEN 'conflicting_payload'
      WHEN c.case_id IS NULL THEN 'unresolved_case'
      WHEN m.golden_customer_id IS DISTINCT FROM c.golden_customer_id THEN 'customer_reference_mismatch'
      WHEN contradicts_account_owner(t.account_id,c.golden_customer_id) THEN 'account_customer_mismatch'
      WHEN note_ts_utc IS NULL OR cast(note_ts_utc AS DATE)>getvariable('snapshot_date') THEN 'invalid_or_future_timestamp'
      WHEN note_text IS NULL THEN 'missing_text'
      ELSE NULL END AS quality_reason
FROM restricted.note_inputs t LEFT JOIN curated.cases c USING(case_id)
LEFT JOIN restricted.identity_map m ON m.source_system='crm' AND m.source_key=t.crm_customer_id
LEFT JOIN restricted.interaction_conflicts x ON x.source='notes' AND x.record_id=t.note_id
QUALIFY row_number() OVER (PARTITION BY note_id ORDER BY payload_hash)=1;

CREATE TABLE curated.contacts AS
SELECT contact_id,case_id,golden_customer_id,account_id,direction,channel,contact_ts_utc,rpc_flag,outcome_code,contact_cost_cad,source_file
FROM restricted.contact_records WHERE quality_reason IS NULL;
CREATE TABLE curated.promises AS
SELECT ptp_id,case_id,golden_customer_id,account_id,ptp_status,ptp_created_ts,ptp_due_date,status_ts,ptp_amount_cad,amount_paid_cad,source_file
FROM restricted.promise_records WHERE quality_reason IS NULL;
CREATE TABLE curated.notes AS
SELECT note_id,case_id,golden_customer_id,account_id,note_ts_utc,source_file
FROM restricted.note_records WHERE quality_reason IS NULL;

CREATE TABLE golden.c360 AS
WITH customers AS (
 SELECT DISTINCT golden_customer_id FROM restricted.identity_map WHERE source_system='crm' AND status='accepted'
), accounts AS (
 SELECT golden_customer_id,count(*) AS linked_accounts,
        count(*) FILTER(WHERE source_system IN ('cards','lending')) AS credit_loan_accounts,
        count(balance_cad) FILTER(WHERE source_system IN ('cards','lending')) AS known_credit_loan_balances,
        sum(balance_cad) FILTER(WHERE source_system IN ('cards','lending')) AS credit_loan_outstanding_cad,
        count(*) FILTER(WHERE source_system='core_banking') AS deposit_accounts,
        sum(balance_cad) FILTER(WHERE source_system='core_banking') AS deposit_balance_cad,
        sum(past_due_cad) FILTER(WHERE source_system IN ('cards','lending')) AS credit_loan_past_due_cad,
        max(dpd) AS max_account_dpd
 FROM curated.accounts GROUP BY 1
), cases AS (
 SELECT golden_customer_id,count(*) AS linked_cases,count(*) FILTER(WHERE case_status='open') AS open_cases,
        bool_or(hardship_flag) AS recorded_hardship_flag
 FROM curated.cases GROUP BY 1
)
SELECT c.golden_customer_id,getvariable('snapshot_date') AS as_of_date,'c360-v0.1' AS definition_version,
       coalesce(a.linked_accounts,0) AS linked_accounts,coalesce(a.credit_loan_accounts,0) AS credit_loan_accounts,
       coalesce(a.known_credit_loan_balances,0) AS known_credit_loan_balances,a.credit_loan_outstanding_cad,
       coalesce(a.deposit_accounts,0) AS deposit_accounts,a.deposit_balance_cad,a.credit_loan_past_due_cad,a.max_account_dpd,
       coalesce(k.linked_cases,0) AS linked_cases,coalesce(k.open_cases,0) AS open_cases,k.recorded_hardship_flag,
       'matched_accounts_only' AS financial_coverage
FROM customers c LEFT JOIN accounts a USING(golden_customer_id) LEFT JOIN cases k USING(golden_customer_id);

-- Transcript files must agree with the approved case and any resolved contact record.
-- Missing contact metadata is unknown linkage, never a fabricated validated link.
CREATE VIEW curated.transcripts AS
SELECT t.*,c.golden_customer_id,
 CASE WHEN contact.contact_id IS NULL THEN 'unknown' ELSE 'validated' END AS contact_link_state
FROM raw.call_transcripts t JOIN curated.cases c USING(case_id)
JOIN golden.c360 g ON g.golden_customer_id=c.golden_customer_id
JOIN restricted.identity_map m ON m.source_system='crm' AND m.source_key=t.crm_customer_id
 AND m.golden_customer_id=c.golden_customer_id AND m.status='accepted'
LEFT JOIN restricted.contact_records contact USING(contact_id)
WHERE try_cast(t.call_start_ts AS DATE)<=g.as_of_date
 AND (contact.contact_id IS NULL OR (contact.quality_reason IS NULL
  AND contact.case_id=t.case_id AND contact.golden_customer_id=c.golden_customer_id));

INSERT INTO restricted.quality_counts
SELECT 'customers','input_rows',count(*) FROM restricted.customer_records
UNION ALL SELECT 'customers','repeated_key_rows',count(*)-count(DISTINCT crm_customer_id) FROM restricted.customer_records WHERE crm_customer_id IS NOT NULL
UNION ALL SELECT 'customers','conflicting_key_rows',count(*) FROM restricted.customer_records WHERE crm_customer_id IN (SELECT crm_customer_id FROM restricted.crm_conflicts)
UNION ALL SELECT 'customers','missing_key_rows',count(*) FROM restricted.customer_records WHERE crm_customer_id IS NULL
UNION ALL SELECT 'customers','missing_or_invalid_dob',count(*) FROM restricted.customer_records WHERE dob IS NULL
UNION ALL SELECT 'customers','missing_or_masked_phone',count(*) FROM restricted.customer_records WHERE phone IS NULL
UNION ALL SELECT 'customers','accepted_duplicate_pointers',count(*) FROM restricted.identity_map WHERE source_system='crm' AND status='accepted' AND match_method='validated_duplicate_pointer'
UNION ALL SELECT 'customers','quarantined_keys',count(*) FROM restricted.identity_map WHERE source_system='crm' AND status='quarantined';

INSERT INTO restricted.quality_counts
SELECT source_system,'input_rows',count(*) FROM restricted.account_inputs GROUP BY 1
UNION ALL SELECT source_system,'invalid_snapshot_rows',count(*) FROM restricted.account_inputs WHERE snapshot_date IS NULL GROUP BY 1
UNION ALL SELECT source_system,'future_snapshot_rows',count(*) FROM restricted.account_inputs WHERE snapshot_date>getvariable('snapshot_date') GROUP BY 1
UNION ALL SELECT source_system,'duplicate_current_rows_removed',count(*)-count(DISTINCT account_id) FROM restricted.account_latest WHERE account_id IS NOT NULL GROUP BY 1
UNION ALL SELECT source_system,coalesce(quality_reason,'accepted_quality'),count(*) FROM restricted.account_records GROUP BY 1,2
UNION ALL SELECT source_system,'served_accounts',count(*) FROM curated.accounts GROUP BY 1;

INSERT INTO restricted.quality_counts
SELECT 'cases','input_rows',count(*) FROM restricted.case_inputs
UNION ALL SELECT 'cases','duplicate_rows_removed',count(*)-count(DISTINCT case_id) FROM restricted.case_inputs WHERE case_id IS NOT NULL
UNION ALL SELECT 'cases',coalesce(quality_reason,'accepted'),count(*) FROM restricted.case_records GROUP BY 2
UNION ALL SELECT 'case_account_links',coalesce(quality_reason,'accepted'),count(*) FROM restricted.case_account_links GROUP BY 2
UNION ALL SELECT 'contacts','input_rows',count(*) FROM restricted.contact_inputs
UNION ALL SELECT 'contacts','duplicate_rows_removed',count(*)-count(DISTINCT contact_id) FROM restricted.contact_inputs WHERE contact_id IS NOT NULL
UNION ALL SELECT 'contacts',coalesce(quality_reason,'accepted'),count(*) FROM restricted.contact_records GROUP BY 2
UNION ALL SELECT 'promises','input_rows',count(*) FROM restricted.promise_inputs
UNION ALL SELECT 'promises','duplicate_rows_removed',count(*)-count(DISTINCT ptp_id) FROM restricted.promise_inputs WHERE ptp_id IS NOT NULL
UNION ALL SELECT 'promises',coalesce(quality_reason,'accepted'),count(*) FROM restricted.promise_records GROUP BY 2
UNION ALL SELECT 'notes','input_rows',count(*) FROM restricted.note_inputs
UNION ALL SELECT 'notes','duplicate_rows_removed',count(*)-count(DISTINCT note_id) FROM restricted.note_inputs WHERE note_id IS NOT NULL
UNION ALL SELECT 'notes',coalesce(quality_reason,'accepted'),count(*) FROM restricted.note_records GROUP BY 2;

CREATE INDEX case_lookup ON curated.cases(case_id);
CREATE INDEX customer_lookup ON golden.c360(golden_customer_id);
CREATE INDEX case_contact_lookup ON curated.contacts(case_id);
CREATE INDEX case_promise_lookup ON curated.promises(case_id);
CREATE INDEX case_note_lookup ON curated.notes(case_id);
