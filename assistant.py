"""Local case assistance with explicit policy gates and append-only review history."""
from datetime import datetime, time, timezone, timedelta
import hashlib
import json
import sqlite3
import duckdb
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from contextlib import closing

from features import read_case
from pipeline import ROOT

POLICY_SOURCES = ['POL-COLL-001 v3.0 §5.1-5.4, §7.3','POL-COLL-004 v4.2 §4.2-4.3','PRC-COLL-012 v1.4 §6.1']


def records(con, sql, parameters=()):
    cursor=con.execute(sql,parameters)
    columns=[c[0] for c in cursor.description]
    return [dict(zip(columns,row)) for row in cursor.fetchall()]


def load_case(con, case_id):
    cases=records(con,'SELECT * FROM curated.cases WHERE case_id=?',[case_id])
    if not cases:
        raise ValueError('Unknown or quarantined case')
    case=cases[0]
    return {'case':case,'features':read_case(con,case_id),
        'customer':records(con,'SELECT * FROM golden.c360 WHERE golden_customer_id=?',[case['golden_customer_id']])[0],
        'controls':records(con,'SELECT * FROM features.contact_controls WHERE golden_customer_id=?',[case['golden_customer_id']])[0],
        'accounts':records(con,'SELECT a.* FROM curated.case_accounts l JOIN curated.accounts a USING(source_system,account_id) WHERE l.case_id=?',[case_id]),
        'attempt_times':[r[0] for r in con.execute("SELECT contact_ts_utc FROM curated.contacts WHERE case_id=? AND direction='outbound' AND channel<>'system' AND contact_ts_utc>=DATE '2026-09-21'",[case_id]).fetchall()],
        'contacts':records(con,'SELECT * FROM curated.contacts WHERE case_id=? ORDER BY contact_ts_utc DESC LIMIT 5',[case_id]),
        'promises':records(con,'SELECT * FROM curated.promises WHERE case_id=? ORDER BY ptp_created_ts DESC LIMIT 5',[case_id])}


def contact_gate(bundle, channel, when):
    """Check at decision time. Snapshot availability is never permission to contact."""
    if channel not in ('call','sms','email'):
        raise ValueError('Unsupported contact channel')
    if when.tzinfo is None:
        raise ValueError('Decision time must include a time zone')
    case,f,q=bundle['case'],bundle['features'],bundle['controls']
    reasons=[]
    state=f['action_eligibility']
    if state not in ('requires_live_policy_check','call_cap_reached'):
        reasons.append(state)
    if case['case_status'] != 'open':
        reasons.append('case_not_open')
    if q.get('consent_'+channel) is not True:
        reasons.append('missing_servicing_consent')
    if channel=='call' and q.get('do_not_call') is not False:
        reasons.append('internal_do_not_call')
    utc=when.astimezone(timezone.utc)
    rolling_attempts=0
    stamps=bundle.get('attempt_times')
    if not isinstance(stamps,(list,tuple)):
        reasons.append('rolling_contact_history_unavailable')
    else:
        for stamp in stamps:
            if not isinstance(stamp,datetime):
                reasons.append('invalid_contact_history_timestamp')
                continue
            # Source TIMESTAMP values are UTC; preserve offsets on aware inputs.
            stamp=stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
            rolling_attempts+=utc-timedelta(days=7)<=stamp<=utc
    if channel=='call':
        cap=case.get('contact_cap_7d')
        if isinstance(cap,bool) or not isinstance(cap,int) or cap<=0:
            reasons.append('invalid_contact_cap')
        elif rolling_attempts>=min(cap,3):
            reasons.append('call_cap_reached')
    try:
        local=when.astimezone(ZoneInfo(q['time_zone']))
    except (ZoneInfoNotFoundError,TypeError,ValueError):
        return {'eligible':False,'reasons':reasons+['unknown_customer_time_zone'],'policy_sources':POLICY_SOURCES}
    if local.date() != f['as_of_date']:
        reasons.append('snapshot_requires_refresh')
    if local.date().isoformat()=='2026-09-30':
        reasons.append('statutory_holiday')
    # ponytail: other statutory holidays need a maintained provincial calendar; fail closed on other dates.
    if channel in ('call','sms'):
        start=max(time(7),q.get('permitted_start') or time(21))
        end=min(time(21),q.get('permitted_end') or time(7))
        if local.weekday()==6:
            if q.get('sunday_permitted') is not True:
                reasons.append('sunday_not_permitted')
            start,end=max(start,time(13)),min(end,time(17))
        if not start<=local.time()<end:
            reasons.append('outside_permitted_hours')
    return {'eligible':not reasons,'reasons':list(dict.fromkeys(reasons)),
        'local_time':local.isoformat(),'rolling_attempts_7d':rolling_attempts,'policy_sources':POLICY_SOURCES,
        'frequency_count_scope':'Conservative count of all recorded outbound non-system attempts. Payment-reminder purpose is unavailable; this can block contact beyond the supplied call/reminder cap.',
        'scope':'review only; no outreach is executed'}


def draft_brief(bundle, channel, when):
    f,c=bundle['features'],bundle['case']
    gate=contact_gate(bundle,channel,when)
    sources=[f"case:{c['case_id']}",f"customer:{c['golden_customer_id']}"]
    sources.extend('account:'+a['account_id'] for a in bundle['accounts'])
    sources.extend('promise:'+p['ptp_id'] for p in bundle['promises'])
    sources.extend(f"{e['kind']}:{e['source_id']}" for e in json.loads(f['text_sources']))
    if not gate['eligible']:
        action='Review the contact restrictions with the assigned employee before taking any contact action.'
    elif f['hardship_mention'] is True or c['hardship_flag'] is True:
        action='Review eligible hardship support with a specialist before requesting a payment. Programme eligibility still needs verification.'
    elif f['callback_request'] is True:
        action='Review the requested callback and confirm the customer’s preferred time before contact.'
    else:
        action='Review the existing payment arrangement and contact history before discussing an affordable next step.'
    amount=f['case_overdue_cad']
    summary=f"Case {c['case_id']} is {c['case_status']}, with {f['case_max_dpd']} days past due and CAD {amount if amount is not None else 'unknown'} overdue. "
    summary+=f"There are {f['broken_ptp_90d']} recorded broken promises in the defined 90-day window and {f['contact_attempts_7d']} outbound attempts in the 7-day window. "
    summary+=f"Account linkage is {f['account_coverage']}. Financial totals cover matched accounts only."
    return {'case_id':c['case_id'],'summary':summary,'proposed_step':action,'contact_gate':gate,
        'sources':list(dict.fromkeys(sources+POLICY_SOURCES)),
        'feature_version':f['definition_version'],'as_of_date':str(f['as_of_date']),
        'generator':'deterministic-v0.1','requires_human_review':True}


def _verify_review_chain(db):
    previous='0'*64
    count=0
    for sequence,payload,stored_previous,digest in db.execute('SELECT sequence,payload,previous_hash,record_hash FROM reviews ORDER BY sequence'):
        if not isinstance(payload,str) or stored_previous!=previous or hashlib.sha256((previous+payload).encode()).hexdigest()!=digest:
            raise ValueError(f'Review audit integrity check failed at sequence {sequence}; no new review was recorded')
        previous=digest
        count+=1
    return {'reviews_checked':count,'last_hash':previous}


def verify_review_log(audit_path=ROOT/'data/reviews.sqlite'):
    """Detect a broken chain. Recomputed hashes or truncation require an external anchor."""
    if not audit_path.exists():
        return {'valid':True,'reviews_checked':0,'last_hash':'0'*64,'scope':'No review log exists.'}
    try:
        with closing(sqlite3.connect(audit_path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            report=_verify_review_chain(db)
        return {'valid':True,**report,'scope':'Local chain integrity only; whole-chain rewriting or trailing deletion is not detectable without an external anchor.'}
    except (sqlite3.Error,ValueError) as error:
        return {'valid':False,'error':str(error),'scope':'Local review log could not be verified.'}


def support_options(con,bundle):
    """Screen supplied programme versions; every candidate still needs eligibility review."""
    case=bundle['case']
    try:
        programmes=records(con,"""SELECT * FROM raw.hardship_programs
            WHERE try_cast(effective_from AS DATE)<=? AND try_cast(effective_to AS DATE)>=?
            ORDER BY program_id,version""",[bundle['features']['as_of_date']]*2)
    except duckdb.CatalogException:
        return []
    accounts=[a for a in bundle.get('accounts',[]) if a.get('account_id')==case.get('primary_account_id')]
    dpd=accounts[0].get('dpd') if len(accounts)==1 else None
    options=[]
    for programme in programmes:
        try:
            products=json.loads(programme['product_types'])
        except (ValueError,TypeError):
            continue
        if not isinstance(products,list) or case.get('primary_product') not in products:
            continue
        checks=['Confirm documented hardship level: '+str(programme['min_hardship_level']),
            'Verify minimum months on book: '+str(programme['min_months_on_book']),
            'Check programme uses in 12 months against maximum: '+str(programme['max_uses_12m']),
            'Confirm required approval level: '+str(programme['approver_level'])]
        excluded=[]
        policy_conflicts=[]
        maximum=programme.get('max_dpd')
        try:
            if maximum is not None and int(maximum)<0 or dpd is not None and int(dpd)<0:
                raise ValueError('Negative DPD')
            if dpd is not None and maximum is not None and int(dpd)>int(maximum):
                excluded.append('Matched primary account DPD exceeds the programme maximum.')
            elif dpd is None or maximum is None:
                checks.append('Verify primary-account DPD and programme DPD maximum.')
        except (ValueError,TypeError):
            checks.append('Programme or account DPD is invalid; verify source evidence.')
            policy_conflicts.append('Invalid programme or account DPD prevents the published DPD screen.')
        for field,description in [('excludes_insolvency','Check insolvency exclusions against current records.'),
                                  ('excludes_broken_plan_90d','Check broken hardship-plan history, distinct from promises to pay.'),
                                  ('requires_income_evidence','Obtain the required income evidence.')]:
            value=str(programme.get(field)).lower()
            if value=='true':
                checks.append(description)
            elif value!='false':
                checks.append('Verify unknown programme requirement: '+field)
        if case.get('insolvency_hold_flag') is True:
            excluded.append('Recorded insolvency hold excludes hardship programmes under POL-COLL-004 v4.2 §4.2 and POL-COLL-001 v3.0 §7.3, regardless of catalogue flags.')
        if str(programme.get('excludes_insolvency')).lower()!='true':
            policy_conflicts.append('The catalogue insolvency exclusion disagrees with, or cannot confirm, the supplied policy prohibition for bankruptcy and consumer proposals.')
        # The supplied policy gives an explicit evidence exemption for short
        # programmes. Surface catalogue contradictions instead of choosing a rule.
        duration=programme.get('duration_months')
        try:
            duration=int(duration)
            if duration<=0:
                raise ValueError('Invalid duration')
            if duration<=3 and str(programme.get('requires_income_evidence')).lower()=='true':
                policy_conflicts.append('Catalogue requires income evidence, but POL-COLL-004 v4.2 §4.3 exempts programmes of three months or less.')
        except (ValueError,TypeError):
            duration=None
            checks.append('Verify programme duration; the short-programme income-evidence exemption cannot be checked.')
        if programme['program_id'] in ('HP-LOAN-EXT','HP-DMP') and str(programme.get('requires_income_evidence')).lower()!='true':
            policy_conflicts.append('POL-COLL-004 v4.2 §4.3 requires income and expense evidence for term extensions and debt management plans; the catalogue requirement disagrees or is unknown.')
        if sum(p['program_id']==programme['program_id'] for p in programmes)>1:
            checks.append('Overlapping effective versions require policy-owner resolution.')
            policy_conflicts.append('More than one effective version exists for this programme.')
        options.append({'program_id':programme['program_id'],'version':programme['version'],
            'program_name':programme['program_name'],'published_terms':programme['description'],
            'review_state':'screened_out' if excluded else 'requires_policy_resolution' if policy_conflicts else 'candidate_pending_eligibility_review',
            'policy_conflicts':policy_conflicts,'duration_months':duration,
            'exclusion_reasons':excluded,'remaining_checks':checks,'approval_level':programme['approver_level'],
            'max_dpd':maximum,'primary_account_dpd':dpd,
            'source':'raw.hardship_programs:'+programme['program_id']+' version '+programme['version']+' '+str(programme['policy_section']),
            'scope':'Snapshot-effective primary-product catalogue screen, not approval or a customer offer.'})
    return options


def reviewed_checklist(call, observations):
    """Attach employee observations without converting detector output into a verdict."""
    codes={row['item_code'] for row in call['qa']}
    if len(codes)!=10 or set(observations)!=codes:
        raise ValueError('Review observations must match all ten items of this transcript.')
    allowed={'not_reviewed','meets_criterion','issue_observed','not_applicable','cannot_determine'}
    checked={}
    for code, observation in observations.items():
        if not isinstance(observation,dict):
            raise ValueError('Invalid checklist observation.')
        outcome=observation.get('outcome')
        note=observation.get('note','')
        if outcome not in allowed or not isinstance(note,str) or len(note)>1200:
            raise ValueError('Invalid checklist outcome or evidence note.')
        if outcome not in ('not_reviewed','cannot_determine') and not note.strip():
            raise ValueError('Explain the evidence or applicability for each decided checklist item.')
        checked[code]={'outcome':outcome,'note':note.strip()}
    return {**call,'employee_checklist':checked,
        'checklist_reviewed_count':sum(v['outcome']!='not_reviewed' for v in checked.values()),
        'checklist_scope':'Employee observations on this transcript, not an automated compliance certification.'}


def save_review(actor, brief, decision, edited_step='', reason='', audit_path=ROOT/'data/reviews.sqlite'):
    if decision not in ('accept','edit','reject') or not actor or len(actor)>100:
        raise ValueError('Invalid reviewer or decision')
    if decision=='edit' and not edited_step.strip():
        raise ValueError('An edited step is required')
    # Accepting records review only. It cannot override contact gates or execute an action.
    payload={'review_id':str(uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),
        'actor':actor,'decision':decision,'brief':brief,'edited_step':edited_step,'reason':reason,
        'executed':False}
    audit_path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(audit_path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS reviews(sequence INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT NOT NULL,previous_hash TEXT NOT NULL,record_hash TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        # ponytail: verify O(n) local history per append; anchor externally and checkpoint if volume grows.
        previous=_verify_review_chain(db)['last_hash']
        encoded=json.dumps(payload,sort_keys=True,default=str)
        digest=hashlib.sha256((previous+encoded).encode()).hexdigest()
        db.execute('INSERT INTO reviews(payload,previous_hash,record_hash) VALUES (?,?,?)',[encoded,previous,digest])
    return payload['review_id']
