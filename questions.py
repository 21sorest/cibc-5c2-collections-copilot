"""Scoped question catalogue. Questions select trusted SQL, never execute user SQL."""
import argparse
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
import json
import re

import duckdb
from assistant import records, load_case, contact_gate
from features import safe_file
from pipeline import ROOT, DEFAULT_RELEASE
from text_signals import normalize, redact
from access import authorize_case

SNAPSHOT=date(2026,9,28)
MONTHS={name.lower():i for i,name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower():i for i,name in enumerate(calendar.month_abbr) if name})
MONTHS['sept']=9
PROTECTED_CONTEXT=r'\b(?:gender|citizenship|religion|religious|marital|married|divorced|immigrant|nationality|ethnicity|race|disability|accessibility|handicape|citoyennete|religieux|marie|divorce)\b|\bi am (?:a woman|a man|\d+ years old)\b'
SUBSET_FILTER=r'\b(?:filter|where|only|ontario|quebec|alberta|manitoba|saskatchewan|british columbia|nova scotia|new brunswick|newfoundland|labrador|prince edward island|yukon|nunavut|northwest territories)\b'
GEOGRAPHIC_FILTER=r'\b(?:ontario|quebec|alberta|manitoba|saskatchewan|british columbia|nova scotia|new brunswick|newfoundland|labrador|prince edward island|yukon|nunavut|northwest territories)\b'


def refused(reason):
    return {'answer':reason,'sql_or_sources':'scope-policy-v0.1','refused':True}


def month_bounds(question):
    question=question.lower()
    question=re.sub(r'\bmay\s+(?=(?:i|we|you)\b)','can ',question)
    found=[number for name,number in MONTHS.items() if re.search(r'\b'+name+r'\b',question)]
    years=re.findall(r'\b20\d\d\b',question)
    year=int(years[0]) if years else 2026
    if len(set(years))>1:
        raise ValueError('Multiple years are not supported by this catalogue')
    # Explicit day ranges are inclusive; SQL uses an exclusive upper boundary.
    names='|'.join(sorted(MONTHS,key=len,reverse=True))
    same=re.search(r'between\s+(\d{1,2})\s+and\s+(\d{1,2})\s+('+names+r')\s+(20\d\d)',question)
    cross=re.search(r'between\s+(\d{1,2})\s+('+names+r')\s+and\s+(\d{1,2})\s+('+names+r')\s+(20\d\d)',question)
    if same:
        start=date(int(same[4]),MONTHS[same[3]],int(same[1]))
        end=date(int(same[4]),MONTHS[same[3]],int(same[2]))+timedelta(days=1)
    elif cross:
        start=date(int(cross[5]),MONTHS[cross[2]],int(cross[1]))
        end=date(int(cross[5]),MONTHS[cross[4]],int(cross[3]))+timedelta(days=1)
    else:
        start=end=None
    if start:
        if end<=start:
            raise ValueError('The requested date range is reversed.')
        return start,end
    first,last=(min(found),max(found)) if found else (9,9)
    start=date(year,first,1)
    end=date(year+1,1,1) if last==12 else date(year,last+1,1)
    return start,end


def sql_answer(con,sql,params=()):
    result=records(con,sql,params)
    if len(result)>100:
        return refused('Result is too large for the approved aggregate interface.')
    if not result:
        answer='No records matched the requested filters.'
    else:
        import io
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=list(result[0]))
        writer.writeheader()
        writer.writerows(result)
        answer=output.getvalue().strip()
    return {'answer':answer,'sql_or_sources':sql+'\nParameters: '+json.dumps(params,default=str),'refused':False,
        'rows':result,'method':'trusted SQL catalogue; supplied source snapshot'}


def policy_answer(con,doc_id,section,release,language='EN'):
    if language not in ('EN','FR'):
        return refused('The requested policy language is unsupported.')
    docs=records(con,"SELECT doc_id,version,title,file_path FROM raw.reference_documents WHERE doc_id IN (?,?) AND language=? AND superseded_by IS NULL AND try_cast(effective_date AS DATE)<=?",[doc_id,doc_id+'-FR',language,SNAPSHOT])
    if len(docs)!=1:
        return refused('An unambiguous applicable policy source could not be found.')
    doc=docs[0]
    try:
        text=safe_file(release,doc['file_path']).read_text(encoding='utf-8')
    except (OSError,ValueError):
        return refused('The applicable policy file is unavailable or outside the approved release.')
    if section:
        requested=(section,) if isinstance(section,str) else tuple(section)
        sections=re.split(r'(?m)(?=^## )',text)
        found=[]
        for key in requested:
            matching=[part for part in sections if re.match(r'^## '+re.escape(key)+r'(?:\s|$)',part)]
            if len(matching)!=1:
                return refused('The requested policy section is missing or ambiguous in the requested language.')
            found.extend(matching)
        if not found:
            return refused('The requested policy section is missing.')
        text='\n\n'.join(found)
    label=', '.join(requested) if section else ''
    return {'answer':text.strip(),'sql_or_sources':f"{doc['doc_id']} v{doc['version']} {label} ({doc['file_path']})",'refused':False,'method':'extractive applicable-policy retrieval; no eligibility approval'}


def transcript_answer(con,case_id,release):
    row=records(con,"""SELECT t.transcript_id,t.file_path FROM curated.transcripts t
        WHERE t.case_id=? AND try_cast(t.call_start_ts AS DATE)<=?
        ORDER BY try_cast(t.call_start_ts AS TIMESTAMP) DESC LIMIT 1""",[case_id,SNAPSHOT])
    if not row:
        return refused('No recorded call is available for this case.')
    body=json.loads(safe_file(release,row[0]['file_path']).read_text(encoding='utf-8'))
    evidence=financial_call_evidence(body['turns'],omit_personal_context=True)
    if not evidence:
        return refused('No account-discussion evidence could be separated from identity verification in this call.')
    summary='Customer statements after the account-discussion purpose, from the most recent recorded call. Agent proposals and brief acknowledgments are evidence for review, not independently verified payment commitments:\n'+'\n'.join(evidence)
    return {'answer':summary,'sql_or_sources':f"transcript:{row[0]['transcript_id']} ({row[0]['file_path']}); customer turn timestamps",'refused':False,'method':'extractive transcript evidence; requires human review'}


def financial_call_evidence(turns,omit_personal_context=False):
    # ponytail: request/response filtering is not full PII detection; employee review remains required.
    # Verification answers can span several customer turns and recur after disclosure.
    identity=r'date (?:of birth|de naissance)|birth date|\bdob\b|identity|identite|security (?:question|answer)|(?:confirm|verify|verification|confirme|verifie).{0,60}(?:email|courriel|phone|telephone|address|adresse|name|nom|account number|numero de compte)|(?:email|courriel|phone|telephone|address|adresse|account number|numero de compte).{0,45}(?:confirm|verify|confirme|verifie)'
    def verification(turn):
        return bool(re.search(identity,normalize(turn['text'])))
    purpose=[float(t['start_sec']) for t in turns if t['speaker']=='agent' and not verification(t) and re.search(r'account|past due|balance|payment|compte|solde|paiement',normalize(t['text']))]
    if not purpose:
        return []
    cutoff=min(purpose)
    output=[]
    previous=None
    verifying=False
    def excerpt(text):
        return '[Personal context omitted; review relevant financial evidence in the recording.]' if omit_personal_context and re.search(PROTECTED_CONTEXT,normalize(text)) else redact(text)
    for turn in turns:
        if turn['speaker']=='agent':
            verifying=verification(turn)
        if verifying or (turn['speaker']=='customer' and re.search(r'date of birth|date de naissance|\bdob\b',normalize(turn['text']))):
            previous=None
            continue
        if turn['speaker']=='customer' and float(turn['start_sec'])>=cutoff:
            if previous and len(turn['text'])<35 and re.search(r'payment|plan|option|link|confirm|call back',normalize(previous['text'])):
                if len(output)+2>24:
                    break
                output.append(f"[{previous['start_sec']}s] Agent context, not customer commitment: {excerpt(previous['text'])}")
            if len(output)>=24:
                break
            output.append(f"[{turn['start_sec']}s] Customer: {excerpt(turn['text'])}")
        previous=turn
    return output


def case_answer(con,case_id,question):
    bundle=load_case(con,case_id)
    f,c=bundle['features'],bundle['case']
    if re.search(r'restriction|consent|eligible|permitted|contact.*(?:can|may)|can.*contact',question):
        now=datetime.now(timezone.utc)
        facts={'decision_time':now.isoformat(),'contact_checks':{channel:contact_gate(bundle,channel,now) for channel in ('call','sms','email')},
            'scope':'Current-time checks over supplied snapshot; stale evidence blocks contact. Employee review does not execute an action.'}
    elif re.search(r'promise|ptp',question):
        promises=bundle['promises']
        if re.search(r'\bopen\b',question):
            promises=records(con,"SELECT * FROM curated.promises WHERE case_id=? AND ptp_status='open' AND ptp_created_ts<DATE '2026-09-29' ORDER BY ptp_due_date NULLS LAST,ptp_created_ts DESC",[case_id])
        if len(promises)>100:
            raise ValueError('Promise results exceed the approved case interface limit; request employee review.')
        facts={'recent_promises':promises,'promise_scope':'all currently open promises' if re.search(r'\bopen\b',question) else 'latest five recorded promises, any status',
            'broken_ptp_90d':f['broken_ptp_90d'],'kept_ptp_rate_90d':f['kept_ptp_rate_90d'],'open_ptp_days_to_due':f['open_ptp_days_to_due']}
    elif re.search(r'feature|signal',question):
        from features import FEATURE_NAMES
        facts={name:f[name] for name in FEATURE_NAMES}
    else:
        facts={'case_id':case_id,'case_status':c['case_status'],'case_max_dpd':f['case_max_dpd'],
            'case_overdue_cad':f['case_overdue_cad'],'customer_c360':bundle['customer'],
            'coverage':'Customer financial totals include accepted matching accounts only; deposit balances and credit/loan amounts remain separate.'}
    return {'answer':json.dumps(facts,indent=2,default=str),'sql_or_sources':f"case:{case_id}; golden.c360:{c['golden_customer_id']}; features.case_current {f['definition_version']}; curated.promises when applicable; assistant.contact_gate for restrictions",
        'refused':False,'method':'Approved scoped case/C360 lookup; no raw identity fields or generated SQL'}


def answer(con,question,release=DEFAULT_RELEASE,actor=None):
    def run_sql(sql,params=()):
        if actor and actor['role']!='supervisor':
            return refused('Aggregate analytics requires the supervisor role. Agents can inspect their assigned cases and supplied policies.')
        if re.search(GEOGRAPHIC_FILTER,normalize(q)) or re.search(r'\b(?:early|mid|late)[ -]stage\s+(?:queue|cases?)\b|\b(?:queue|bucket)\s*(?:=|(?:is|equals|named)\b)',q):
            return refused('This aggregate catalogue does not support the requested geographic or named-queue subset. No broader aggregate was substituted.')
        return sql_answer(con,sql,params)
    if not isinstance(question,str) or not question.strip() or len(question)>2000:
        return refused('Enter a collections question of at most 2,000 characters.')
    q=question.lower().strip()
    q=re.sub(r'\bmay\s+(?=(?:i|we|you)\b)','can ',q)
    historical=re.search(r'as of (\d{4}-\d{2}-\d{2})',q)
    if historical and historical[1]!=SNAPSHOT.isoformat():
        return refused('This interface only supports the supplied 2026-09-28 snapshot for as-of questions.')
    language='FR' if re.search(r'answer in french|respond in french|reply in french|repond.*francais',normalize(q)) else 'EN'
    prohibited_policy_request=bool(re.search(r'rank|export|list.*customer|priorit|score|predict|(?:select|identify).*customer|(?:call|contact).*first|deny|stop offering|ignore.*instructions|\bdrop\s+(?:table|schema|database)|\bdelete\s+from|\binsert\s+into|\b(?:pragma|attach)\b',q))
    if re.search(r'policy|guideline|safeguard',q) and re.search(r'vulnerab|disability|accessibility|protected (?:attributes|grounds)',q) and re.search(r'support|require|must|should|guidance|handling|safeguard|rules',q) and not prohibited_policy_request:
        result=policy_answer(con,'POL-COLL-004',('§4.5','§4.6'),release,language)
        if not result['refused']:
            result['answer']='Policy guidance for employee review. Protected grounds do not authorize automated ranking, repayment prediction, exports or customer prioritization. This answer grants no contact or assignment permission.\n\n'+result['answer']
        return result
    if re.search(r'protected (?:attributes|grounds)',q) and re.search(r'policy|never|must not|should not|forbidden|not use',q) and not prohibited_policy_request:
        return policy_answer(con,'POL-COLL-004','§4.6',release,language)
    if re.search(r'vulnerab',q) and re.search(r'priorit|bottom|rank|repayment|predict|rarely pay|call queue',q):
        return refused('Customer queue rankings or repayment predictions using protected attributes are outside the approved scope.')
    if re.search(r'citizenship|gender|marital|newcomer|nationality|ethnicity|religion|church|date of birth|home address|phone number|disability|accessibility|\brace\b|\baccent\b|\bhousehold\b|\bby age\b|\bfsas?\b|postal areas|names and phone|export.*(?:name|phone|email)|\bdrop\s+(?:table|schema|database)|\bdelete\s+from|\binsert\s+into|\b(?:pragma|attach)\b|ignore.*instructions',q):
        return refused('Bulk personal-data exports and decisions or rankings using protected attributes are outside the approved scope.')
    if re.search(r'weather|\bsue\b|legal advice',q):
        return refused('This assistant supports collections data and supplied policies. It cannot provide weather forecasts or decide legal action.')
    case_ids=set(re.findall(r'\bCS-\d{4}-\d+\b',question,re.I))
    if len({value.upper() for value in case_ids})>1:
        return refused('This interface supports one authorized case at a time; no first-case answer was substituted for a multi-case comparison.')
    case=re.search(r'\bCS-\d{4}-\d+\b',question,re.I)
    if case:
        if actor:
            try:
                authorize_case(con,actor,case[0].upper())
            except PermissionError as error:
                return refused(str(error))
        temporal_scope=re.sub(r'\bcs-\d{4}-\d+\b','',q)
        temporal_scope=re.sub(r'\bas of 2026-09-28\b','',temporal_scope)
        named_case_month=any(re.search(r'\b'+name+r'\b',temporal_scope) for name in MONTHS if name!='may')
        if named_case_month or re.search(r'\b20\d\d\b|\b(?:in|during|from|since|before|after|for|of)\s+may\b|\b(?:last|previous|next)\s+(?:month|year|week)\b',temporal_scope):
            return refused('Date-filtered case history is outside this interface. Request current case facts or explicit as of 2026-09-28; no current facts were substituted for another period.')
        if re.search(r'recorded call|transcript|customer.*(?:say|agree)|summari.*call|call.*summar',q):
            return transcript_answer(con,case[0].upper(),release)
        if re.search(r'balance|overdue|past due|\bdpd\b|promise|\bptp\b|feature|signal|c360|customer (?:view|profile|record)|restriction|consent|eligible|permitted|can.*contact',q):
            try:
                return case_answer(con,case[0].upper(),q)
            except ValueError as error:
                return refused(str(error))
    try:
        start,end=month_bounds(q)
    except ValueError as error:
        return refused(str(error))
    named_month=any(re.search(r'\b'+name+r'\b',q) for name in MONTHS)
    dated_period=named_month or bool(re.search(r'\b20\d\d\b',q))
    if dated_period and start>SNAPSHOT:
        return refused('The requested period is after the supplied 2026-09-28 snapshot. Future outcomes are unavailable.')
    c360_scope=bool(re.search(r'financial coverage|incomplete.*coverage|matched.*coverage|how many.*golden customer|count.*c360 customer|total.*(?:credit|loan).*balance|total.*outstanding.*(?:credit|loan)',q) and re.search(r'customer|c360',q))
    if c360_scope:
        extra_period=re.sub(r'\bas of 2026-09-28\b','',q)
        if any(re.search(r'\b'+name+r'\b',extra_period) for name in MONTHS) or re.search(r'\b20\d\d\b|\b(?:last|previous|next)\s+(?:month|year|week)\b',extra_period):
            return refused('C360 counts and financial totals describe the supplied current snapshot, not another historical period.')
        if re.search(SUBSET_FILTER,q) or re.search(r'\b(?:province|queue|bucket)\b|\b(?:with|having)\s+(?:incomplete|complete|partial|no)\b',q):
            return refused('Subset filters are unsupported for this C360 aggregate. No broader population was substituted.')
    # Catalogue defaults and source fields are explicit. No generated SQL is accepted.
    if 'open' in q and re.search(r'total.*(?:amount )?overdue|how many.*hardship|how many.*insolvency',q):
        if dated_period and not historical:
            return refused('Historical open-case snapshots are unavailable; no current population was substituted.')
        if 'insolvency' in q:
            return run_sql("SELECT count(*) AS open_cases_on_insolvency_hold,sum(try_cast(total_overdue AS DECIMAL(18,2))) AS overdue_cad FROM raw.collections_cases WHERE outcome IS NULL AND try_cast(insolvency_hold_flag AS BOOLEAN) IS TRUE")
        if 'hardship' in q and 'queue' in q:
            return run_sql("SELECT queue,count(*) AS open_hardship_cases FROM raw.collections_cases WHERE outcome IS NULL AND try_cast(hardship_flag AS BOOLEAN) IS TRUE GROUP BY 1 ORDER BY 1")
        if 'overdue' in q and 'product' in q:
            return run_sql("SELECT primary_product,sum(try_cast(total_overdue AS DECIMAL(18,2))) AS overdue_cad FROM raw.collections_cases WHERE outcome IS NULL GROUP BY 1 ORDER BY 1")
        return refused('The requested open-case grouping is unsupported; no broader population was substituted.')
    if 'payment link' in q and 'sms' in q and re.search(r'clicked|click rate',q):
        return run_sql("WITH links AS (SELECT payment_link_id,bool_or(try_cast(link_clicked_flag AS BOOLEAN)) AS clicked FROM raw.contact_history WHERE coalesce(channel_v2,channel)='sms' AND direction='outbound' AND nullif(trim(payment_link_id),'') IS NOT NULL AND try_cast(contact_ts_utc AS DATE)>=? AND try_cast(contact_ts_utc AS DATE)<? GROUP BY 1) SELECT round(100.0*count(*) FILTER (WHERE clicked IS TRUE)/nullif(count(*),0),2) AS sms_payment_link_click_rate_pct,count(*) AS distinct_links_sent,count(*) FILTER (WHERE clicked IS NULL) AS unknown_click_outcomes FROM links",[start,min(end,SNAPSHOT+timedelta(days=1))])
    if 'cured' in q and re.search(r'average|mean',q) and 'days' in q and 'product' in q:
        return run_sql("SELECT primary_product,round(avg(try_cast(days_to_cure AS DOUBLE)),2) AS avg_days_to_cure,count(*) AS cured_cases FROM raw.collections_cases WHERE try_cast(cure_flag AS BOOLEAN) IS TRUE AND try_cast(cure_date AS DATE)>=? AND try_cast(cure_date AS DATE)<? GROUP BY 1 ORDER BY 1",[start,min(end,SNAPSHOT+timedelta(days=1))])
    if re.search(r'financial coverage|incomplete.*coverage|matched.*coverage',q) and re.search(r'customer|c360',q):
        return run_sql('SELECT financial_coverage,count(*) AS customers FROM golden.c360 GROUP BY 1 ORDER BY 1')
    if re.search(r'how many.*golden customer|count.*c360 customer',q):
        return run_sql('SELECT count(*) AS golden_customers FROM golden.c360')
    if re.search(r'total.*(?:credit|loan).*balance|total.*outstanding.*(?:credit|loan)',q) and re.search(r'customer|c360',q):
        if re.search(r'\b(?:province|queue|bucket|filter|where|only|ontario|quebec|alberta|manitoba|saskatchewan|british columbia|nova scotia|new brunswick|newfoundland|labrador|prince edward island|yukon|nunavut|northwest territories)\b',normalize(q)):
            return refused('Geographic, queue and other subset filters are unsupported for this C360 financial total. No broader total was substituted.')
        return run_sql('SELECT sum(credit_loan_outstanding_cad) AS matched_credit_loan_outstanding_cad,sum(known_credit_loan_balances) AS known_account_balances,sum(credit_loan_accounts) AS linked_credit_loan_accounts FROM golden.c360')
    if re.search(r'average.*(?:days past due|dpd)',q) and 'queue' in q:
        if dated_period and not historical:
            return refused('Historical current-DPD snapshots are not available. Request the current supplied snapshot or explicit as of 2026-09-28.')
        return run_sql("SELECT queue,round(avg(try_cast(current_dpd AS DOUBLE)),1) AS avg_dpd,count(*) AS open_cases FROM raw.collections_cases WHERE outcome IS NULL GROUP BY 1 ORDER BY 1")
    if not re.search(r'attempt|contact|average|mean|touches',q) and re.search(r'how many.*cases.*open|open.*cases.*bucket',q):
        if dated_period and not historical:
            return refused('Historical open-case snapshots are not available. Request the current supplied snapshot or explicit as of 2026-09-28.')
        return run_sql("SELECT current_bucket,count(*) AS open_cases FROM raw.collections_cases WHERE outcome IS NULL GROUP BY 1 ORDER BY 1")
    if 'hardship rate' in q and 'product' in q:
        bounds=[start,end] if named_month else [date(start.year,1,1),date(start.year+1,1,1)]
        return run_sql("SELECT primary_product,round(100.0*avg(cast(try_cast(hardship_flag AS BOOLEAN) AS INTEGER)),1) AS hardship_rate_pct,count(*) AS cases FROM raw.collections_cases WHERE try_cast(case_open_date AS DATE)>=? AND try_cast(case_open_date AS DATE)<? GROUP BY 1 ORDER BY 1",bounds)
    if re.search(r'broken.?promise.*previous|broken.?promise.*number',q):
        return run_sql("SELECT least(try_cast(prior_broken_ptp_count AS INTEGER),3) AS prior_broken,round(100.0*avg(CASE WHEN ptp_status='broken' THEN 1 ELSE 0 END),1) AS broken_rate_pct,count(*) AS promises FROM raw.promises_to_pay WHERE ptp_status IN ('kept','partially_kept','broken') GROUP BY 1 ORDER BY 1")
    if re.search(r'promise.?kept rate|promise.kept rate',q) and 'champion' not in q:
        if re.search(r'by (?:the )?channel',q):
            return run_sql("SELECT ptp_channel,round(100.0*sum(CASE WHEN ptp_status='kept' THEN 1 ELSE 0 END)/nullif(count(*),0),1) AS promise_kept_rate_pct,count(*) AS resolved_promises FROM raw.promises_to_pay WHERE ptp_status IN ('kept','partially_kept','broken') AND try_cast(ptp_due_date AS DATE)>=? AND try_cast(ptp_due_date AS DATE)<? GROUP BY 1 ORDER BY 1",[start,end])
        return run_sql("SELECT round(100.0*sum(CASE WHEN ptp_status='kept' THEN 1 ELSE 0 END)/nullif(count(*),0),1) AS promise_kept_rate_pct FROM raw.promises_to_pay WHERE ptp_status IN ('kept','partially_kept','broken') AND try_cast(ptp_due_date AS DATE)>=? AND try_cast(ptp_due_date AS DATE)<?",[start,end])
    if 'broken' in q and 'site' in q:
        return run_sql("SELECT coalesce(a.site,'self_serve') AS site,round(100.0*avg(CASE WHEN p.ptp_status='broken' THEN 1 ELSE 0 END),1) AS broken_rate_pct,count(*) AS promises FROM raw.promises_to_pay p LEFT JOIN raw.agents a ON p.agent_id=a.agent_id WHERE p.ptp_status IN ('kept','partially_kept','broken') AND try_cast(p.ptp_due_date AS DATE)>=? AND try_cast(p.ptp_due_date AS DATE)<? GROUP BY 1 ORDER BY 1",[start,min(end,SNAPSHOT+timedelta(days=1))])
    if re.search(r'paid against promises|collected amount',q):
        return run_sql("SELECT sum(try_cast(amount_paid_against AS DECIMAL(18,2))) AS collected_cad FROM raw.promises_to_pay WHERE try_cast(paid_date AS DATE)>=? AND try_cast(paid_date AS DATE)<?",[start,end])
    if 'late-fee disputes' in q:
        if not ('15' in q and '22' in q and 'september 2026' in q):
            return refused('The incident comparison currently supports 15-22 September 2026 against the preceding eight days only.')
        return run_sql("SELECT CASE WHEN try_cast(contact_ts_local AS TIMESTAMP)>=TIMESTAMP '2026-09-15' THEN '15-22 Sep' ELSE '7-14 Sep' END AS period,count(*) AS disputes FROM raw.contact_history WHERE try_cast(dispute_raised_flag AS BOOLEAN) IS TRUE AND try_cast(contact_ts_local AS TIMESTAMP)>=TIMESTAMP '2026-09-07' AND try_cast(contact_ts_local AS TIMESTAMP)<TIMESTAMP '2026-09-23' GROUP BY 1 ORDER BY 1")
    if 'outside' in q and 'hours' in q and 'province' in q:
        return run_sql("SELECT c.province_code,round(100.0*avg(CASE WHEN try_cast(h.within_permitted_hours_flag AS BOOLEAN) IS FALSE THEN 1 ELSE 0 END),2) AS out_of_hours_pct,count(*) AS calls FROM raw.contact_history h JOIN raw.collections_cases c USING(case_id) WHERE coalesce(h.channel_v2,h.channel)='call' AND h.direction='outbound' AND try_cast(h.contact_ts_local AS DATE)>=? AND try_cast(h.contact_ts_local AS DATE)<? GROUP BY 1 ORDER BY 1",[start,end])
    if 'right-party' in q and 'hour' in q:
        return run_sql("SELECT contact_hour_local,round(100.0*avg(CASE WHEN try_cast(rpc_flag AS BOOLEAN) IS TRUE THEN 1 ELSE 0 END),1) AS rpc_rate_pct,count(*) AS attempts FROM raw.contact_history WHERE coalesce(channel_v2,channel)='call' AND direction='outbound' AND try_cast(contact_ts_local AS DATE)>=? AND try_cast(contact_ts_local AS DATE)<? GROUP BY 1 ORDER BY try_cast(contact_hour_local AS INTEGER)",[start,min(end,SNAPSHOT)])
    if 'active card' in q and re.search(r'past due|delinquen',q):
        return run_sql("SELECT product_code,round(100.0*avg(CASE WHEN try_cast(dpd AS INTEGER)>=1 THEN 1 ELSE 0 END),2) AS delinquency_rate_pct,count(*) AS accounts FROM raw.card_accounts WHERE try_cast(snapshot_date AS DATE)=? AND account_status IN ('active','blocked') AND try_cast(dpd AS INTEGER) IS NOT NULL GROUP BY 1 ORDER BY 1",[SNAPSHOT])
    if re.search(r'rolled|roll rate',q) and 'worse' in q:
        first_month_end=date(start.year,start.month,calendar.monthrange(start.year,start.month)[1])
        last_month_end=end-timedelta(days=1)
        return run_sql("WITH s AS MATERIALIZED (SELECT account_id,product_type,cast(coalesce(try_strptime(month_end_date,'%Y-%m-%d'),try_strptime(month_end_date,'%d/%m/%Y'),try_strptime(month_end_date,'%Y%m%d')) AS DATE) AS month_end,dpd FROM raw.account_monthly_snapshot WHERE dpd IS NOT NULL) SELECT a.product_type,round(100.0*avg(CASE WHEN b.dpd>30 THEN 1 ELSE 0 END),1) AS roll_rate_pct,count(*) AS accounts FROM s a JOIN s b ON a.account_id=b.account_id AND b.month_end=? WHERE a.month_end=? AND a.dpd BETWEEN 1 AND 30 GROUP BY 1 ORDER BY 1",[last_month_end,first_month_end])
    if 'champion' in q and re.search(r'promise|kept',q):
        return run_sql("SELECT c.test_cell,round(100.0*avg(CASE WHEN p.ptp_status='kept' THEN 1 ELSE 0 END),1) AS kept_pct,count(*) AS promises FROM raw.promises_to_pay p JOIN raw.collections_cases c USING(case_id) WHERE c.assignment_method='random' AND c.test_cell IN ('champion','challenger_A','challenger_B') AND p.ptp_status IN ('kept','partially_kept','broken') GROUP BY 1 ORDER BY 1")
    if 'cured within 30' in q:
        return run_sql("SELECT round(100.0*avg(CASE WHEN try_cast(cure_flag AS BOOLEAN) IS TRUE AND try_cast(days_to_cure AS INTEGER)<=30 THEN 1 ELSE 0 END),2) AS cure_30d_pct,count(*) AS cases FROM raw.collections_cases WHERE try_cast(case_open_date AS DATE)>=? AND try_cast(case_open_date AS DATE)<?",[start,end])
    if 'certified' in q and 'cure' in q and 'random' in q:
        return run_sql("SELECT a.vulnerable_customer_certified,round(100.0*avg(CASE WHEN try_cast(c.cure_flag AS BOOLEAN) IS TRUE AND try_cast(c.days_to_cure AS INTEGER)<=30 THEN 1 ELSE 0 END),2) AS cure_30d_pct,count(*) AS cases FROM raw.collections_cases c JOIN raw.agents a ON a.agent_id=c.assigned_agent_id WHERE c.assignment_method='random' AND try_cast(c.hardship_flag AS BOOLEAN) IS TRUE GROUP BY 1 ORDER BY 1")
    if 'charged off' in q:
        if not re.search(r'12 months|last year|past year',q):
            return refused('The write-off catalogue currently supports the 12 months ending 28 September 2026.')
        return run_sql("SELECT product,count(*) AS accounts,sum(amount) AS charged_off_cad FROM (SELECT 'card' AS product,try_cast(chargeoff_date AS DATE) AS event_date,try_cast(chargeoff_amount AS DECIMAL(18,2)) AS amount FROM raw.card_accounts UNION ALL SELECT product_type,try_cast(chargeoff_date AS DATE),try_cast(chargeoff_amount AS DECIMAL(18,2)) FROM raw.loan_accounts) WHERE event_date>? AND event_date<=? GROUP BY 1 ORDER BY 1",[date(2025,9,28),SNAPSHOT])
    if 'cost per contact' in q:
        return run_sql("SELECT coalesce(channel_v2,channel) AS channel,round(sum(try_cast(contact_cost_cad AS DOUBLE))/nullif(count(*),0),2) AS cost_per_contact_cad FROM raw.contact_history WHERE try_cast(contact_ts_utc AS DATE)>=? AND try_cast(contact_ts_utc AS DATE)<? AND coalesce(channel_v2,channel)<>'system' GROUP BY 1 ORDER BY 1",[start,end])
    if 'outbound' in q and re.search(r'attempt|touches',q) and 'bucket' in q:
        return run_sql("WITH attempts AS MATERIALIZED (SELECT case_id,count(*) AS n FROM raw.contact_history WHERE direction='outbound' AND coalesce(channel_v2,channel)<>'system' AND try_cast(contact_ts_utc AS DATE)<=DATE '2026-09-28' GROUP BY 1) SELECT c.current_bucket,round(avg(coalesce(a.n,0)),3) AS attempts_per_case FROM raw.collections_cases c LEFT JOIN attempts a USING(case_id) WHERE c.outcome IS NULL GROUP BY 1 ORDER BY 1")
    if re.search(r'consumer proposal|bankrupt|insolvency',q):
        return policy_answer(con,'POL-COLL-001','§7.3',release,language)
    if re.search(r'income evidence|evidence of income|income proof|proof of income|income documents|term extension|debt management plan',q):
        return policy_answer(con,'POL-COLL-004',('§4.2','§4.3'),release,language)
    if re.search(r'cease|stop (?:calls|calling|contact|texts|emails)|representative|credit counsel|lawyer|trustee',q):
        result=policy_answer(con,'POL-COLL-001','§5.4',release,language)
        if language=='FR' and not result['refused'] and re.search(r'representative|credit counsel|lawyer|trustee',q) and not re.search(r'representant|mandataire|conseill|avocat|syndic',normalize(result['answer'])):
            return refused('The supplied French section omits representative handling. Request the English source or policy review; no untranslated rule was guessed.')
        return result
    if re.search(r'permitted hours|calling hours|contact hours|sunday|statutory holiday|time zone|timezone|what time.*(?:call|contact|text)',q):
        result=policy_answer(con,'POL-COLL-001','§5.1',release,language)
        if language=='FR' and not result['refused'] and 'sunday' in q and 'dimanche' not in normalize(result['answer']):
            return refused('The supplied French section omits Sunday-specific hours. Request the English source or policy review; ordinary hours were not substituted.')
        return result
    if re.search(r'preferred language|french.*(?:contact|call|customer)|(?:contact|call).*french',q):
        return policy_answer(con,'POL-COLL-001','§5.5',release,language)
    if re.search(r'casl|consent|do not call list|\bdncl\b',q):
        return policy_answer(con,'POL-COLL-001','§5.3',release,language)
    if re.search(r'how many.*(?:attempt|call)|contact frequency',q):
        return policy_answer(con,'POL-COLL-001','§5.2',release,language)
    if re.search(r'disput|payment.*not applied|fraud|late.fees?.*(?:bank|system).*incident',q):
        return policy_answer(con,'PRC-COLL-012','§6.2' if re.search(r'bank.*incident|system incident|late.fee.*incident',q) else '§6.1',release,language)
    if re.search(r'complaint|dissatisfaction|ombudsman',q):
        return policy_answer(con,'POL-COLL-007',('§8.1','§8.2'),release,language)
    if re.search(r'read back|confirm.*promise|taking a promise|promise.*(?:amount and date|21 days|due date)|payment link',q):
        return policy_answer(con,'PRC-COLL-010',('§3.1','§3.2'),release,language)
    if re.search(r'hardship|hours.*cut|reduced payment|reduced.payment|reduced.*programme',q):
        return policy_answer(con,'POL-COLL-004','§4.2',release,language)
    if 'grace period' in q:
        return policy_answer(con,'PRC-COLL-010','§3.3',release,language)
    if '23' in q and '24' in q and re.search(r'volume|drop|dialer',q):
        return policy_answer(con,'IR-2026-0923',None,release)
    return refused('This question is outside the implemented query catalogue. Rephrase using a supported metric or request employee review; no answer has been guessed.')


def benchmark(database=ROOT/'data/collections.duckdb',output=ROOT/'submission/benchmark_answers.csv',extra=None):
    with duckdb.connect(str(database),read_only=True) as con:
        questions=con.execute('SELECT question_id,question_text FROM raw.benchmark_questions ORDER BY question_id').fetchall()
        if extra:
            merged=dict(questions)
            with open(extra,encoding='utf-8-sig',newline='') as source:
                reader=csv.DictReader(source)
                if not {'question_id','question_text'}<=set(reader.fieldnames or []):
                    raise ValueError('Extra questions need question_id and question_text columns')
                for row in reader:
                    key,text=row['question_id'].strip(),row['question_text'].strip()
                    if not key or not text or row.get('as_of_date','2026-09-28') not in ('','2026-09-28'):
                        raise ValueError('Extra questions must be nonempty and use the supported snapshot')
                    if key in merged and merged[key]!=text:
                        raise ValueError('Conflicting duplicate question ID: '+key)
                    merged[key]=text
            questions=sorted(merged.items())
        rows=[]
        errors=[]
        for key,question in questions:
            try:
                result=answer(con,question)
            except Exception as error:
                errors.append({'question_id':key,'error':str(error)})
                result=refused('The source query failed validation; employee review is required.')
            rows.append({'question_id':key,**{field:result[field] for field in ('answer','sql_or_sources','refused')}})
        with output.open('w',encoding='utf-8',newline='') as target:
            writer=csv.DictWriter(target,fieldnames=['question_id','answer','sql_or_sources','refused'])
            writer.writeheader()
            writer.writerows({**row,'refused':str(row['refused']).lower()} for row in rows)
        summary={'questions':len(rows),'answered':sum(not r['refused'] for r in rows),'refused':sum(r['refused'] for r in rows),'errors':errors,
            'note':'Incomplete deterministic catalogue; generated by the application path, not manually edited. Answered does not mean correct.'}
        (ROOT/'reports/benchmark_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question')
    parser.add_argument('--benchmark',action='store_true')
    parser.add_argument('--extra',type=str,help='Additional organizer questions CSV; used with --benchmark')
    args=parser.parse_args()
    if args.benchmark:
        benchmark(extra=args.extra)
    elif args.question:
        with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
            print(json.dumps(answer(con,args.question),indent=2,default=str))
    else:
        parser.error('Provide --question or --benchmark')
