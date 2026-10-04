"""Employee-reviewed action, channel evidence and staff routing; nothing executes."""
from collections import Counter
from datetime import datetime,time,timedelta,timezone
import json
import math
import unicodedata
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
import duckdb
from assistant import contact_gate,records,POLICY_SOURCES,support_options
MIN_CHANNEL_OUTCOMES=20

def wilson(successes,count):
    if not count:return None
    z=1.96;p=successes/count;den=1+z*z/count
    mid=(p+z*z/(2*count))/den
    half=z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/den
    return [max(0,mid-half),min(1,mid+half)]

def safe_records(con,sql,params=()):
    try:return records(con,sql,params)
    except duckdb.Error:return []

def channel_evidence(con,bundle,when,gates):
    f,c=bundle['features'],bundle['case'];cutoff=when.astimezone(timezone.utc).replace(tzinfo=None)
    start=datetime.combine(f['as_of_date']-timedelta(days=89),time())
    end=min(cutoff,datetime.combine(f['as_of_date']+timedelta(days=1),time()))
    histories=safe_records(con,"""SELECT channel,count(*) AS attempts,count(rpc_flag) AS known_rpc,
        sum(CASE WHEN rpc_flag IS TRUE THEN 1 ELSE 0 END) AS rpc
        FROM curated.contacts WHERE case_id=? AND direction='outbound' AND channel IN ('call','sms','email')
        AND contact_ts_utc>=? AND contact_ts_utc<=? GROUP BY channel""",[c['case_id'],start,end])
    history={r['channel']:r for r in histories if all(k in r for k in ('channel','attempts','known_rpc','rpc'))};candidates=[]
    hours={}
    try:
        zone=ZoneInfo(bundle['controls'].get('time_zone'))
        events=safe_records(con,"SELECT channel,contact_ts_utc,rpc_flag FROM curated.contacts WHERE case_id=? AND direction='outbound' AND contact_ts_utc>=? AND contact_ts_utc<=?",[c['case_id'],start,end])
        for event in events:
            stamp=event['contact_ts_utc'].replace(tzinfo=timezone.utc).astimezone(zone)
            key=(event['channel'],stamp.hour)
            item=hours.setdefault(key,{'hour_local':stamp.hour,'attempts':0,'known_rpc':0,'rpc':0})
            item['attempts']+=1;item['known_rpc']+=event['rpc_flag'] is not None;item['rpc']+=event['rpc_flag'] is True
    except (ZoneInfoNotFoundError,ValueError,TypeError,KeyError,AttributeError):
        hours={}
    for channel,gate in gates.items():
        envelope=safe_records(con,"""SELECT time_band,capacity_units,used_units,unit_cost_cad,outage_flag
            FROM raw.channel_capacity WHERE channel=? AND try_cast(date AS DATE)=?""",[channel,f['as_of_date']])
        operational=[];descriptive_costs=[];unavailable=Counter()
        local=gate.get('local_time')
        local_hour=datetime.fromisoformat(local).hour+datetime.fromisoformat(local).minute/60 if local else None
        for entry in envelope:
            try:
                band=entry['time_band']
                if band!='all_day':
                    a,b=(int(v) for v in band.split('-'))
                    if not 0<=a<b<=24:raise ValueError()
                    if local_hour is None or not a<=local_hour<b:
                        unavailable['outside_capacity_time_band']+=1;continue
                outage=str(entry['outage_flag']).lower()
                if outage!='false':
                    unavailable['outage_or_unknown_outage']+=1;continue
                cost_value=float(entry['unit_cost_cad'])
                if not math.isfinite(cost_value) or cost_value<0:raise ValueError()
                descriptive_costs.append(cost_value)
                capacity=int(entry['capacity_units']);used=int(entry['used_units'])
                if capacity<=0 or used<0:raise ValueError()
                if used>=capacity:unavailable['capacity_exhausted']+=1;continue
                operational.append({'cost':cost_value,'remaining_units':capacity-used,'time_band':band})
            except (KeyError,TypeError,ValueError):unavailable['capacity_or_cost_unknown_invalid']+=1
        available=min(operational,key=lambda r:r['cost']) if operational else None
        descriptive_cost=min(descriptive_costs) if descriptive_costs else None
        cost=available['cost'] if available else descriptive_cost
        row=history.get(channel);known=int(row['known_rpc']) if row else 0;rpc=int(row['rpc']) if row else 0
        interval=wilson(rpc,known);rate=rpc/known if known else None
        evidence=('incomplete_outcomes' if row and int(row['attempts'])>known else
            'sufficient_descriptive_sample' if known>=MIN_CHANNEL_OUTCOMES else 'sparse' if known else 'unavailable')
        score=cost/interval[0] if cost is not None and interval and interval[0]>0 and known>=MIN_CHANNEL_OUTCOMES else None
        candidates.append({'channel':channel,'policy_eligible':gate['eligible'],'eligible':gate['eligible'] and available is not None,
            'reasons':gate['reasons']+([] if available else ['current_capacity_unavailable']),
            'observed_rpc_rate_90d':rate,'observed_attempts':int(row['attempts']) if row else None,
            'known_rpc_count':known if row else None,'observed_rpc':rpc if row else None,'rpc_interval_95':interval,
            'missing_rpc_outcomes':int(row['attempts'])-known if row else None,
            'evidence_state':evidence,'snapshot_unit_cost_cad':cost,
            'descriptive_snapshot_unit_cost_cad':descriptive_cost,'operational_unit_cost_cad':available['cost'] if available else None,
            'descriptive_cost_per_observed_rpc_proxy':descriptive_cost/rate if descriptive_cost is not None and rate else None,'cost_per_observed_rpc_proxy':cost/rate if cost is not None and rate else None,
            'ranking_proxy':score,'ranking_basis':'snapshot unit cost / Wilson lower bound; minimum 20 known RPC outcomes',
            'capacity_state':'snapshot_available_confirm_live' if available else 'blocked_unknown_outage_exhaustion_or_time_band',
            'capacity_exclusions':dict(unavailable),'capacity_evidence':available,
            'history_cutoff_utc':end.isoformat(),'local_decision_time':gate.get('local_time'),
            'timing_evidence':[value for (ch,hour),value in sorted(hours.items()) if ch==channel],
            'timing_limitation':'Descriptive clock hours using current customer timezone; sparse outcomes cannot identify a best hour.',
            'descriptive_cost_per_rpc_interval_95':[descriptive_cost/interval[1],descriptive_cost/interval[0]] if descriptive_cost is not None and interval and interval[0]>0 else None,
            'cost_per_rpc_interval_95':[cost/interval[1],cost/interval[0]] if cost is not None and interval and interval[0]>0 else None})
    comparable=sorted([r for r in candidates if r['descriptive_cost_per_observed_rpc_proxy'] is not None],key=lambda r:(r['descriptive_cost_per_observed_rpc_proxy'],r['channel']))
    comparison=[]
    for row in comparable:
        unmet=list(row['reasons'])
        if row['evidence_state']!='sufficient_descriptive_sample':unmet.append('sparse_or_incomplete_outcome_evidence')
        comparison.append({'channel':row['channel'],'descriptive_cost_per_observed_rpc':row['descriptive_cost_per_observed_rpc_proxy'],
            'operational_unit_cost_cad':row['operational_unit_cost_cad'],
            'cost_basis':'Descriptive columns can include unavailable envelopes; operational columns use an available matching envelope only.',
            'cost_per_rpc_interval_95':row['descriptive_cost_per_rpc_interval_95'],
            'operational_or_conditional_cost_per_rpc_interval_95':row['cost_per_rpc_interval_95'],'known_rpc_count':row['known_rpc_count'],
            'evidence_state':row['evidence_state'],'unmet_prerequisites':unmet,
            'scope':'Descriptive investigation order only; does not grant contact permission.'})
    usable=sorted([r for r in comparable if r['evidence_state']=='sufficient_descriptive_sample' and r['policy_eligible']],key=lambda r:(r['cost_per_observed_rpc_proxy'],r['channel']))
    preferred=None
    if usable and len(usable)==sum(r['policy_eligible'] for r in candidates):
        first=usable[0];bounds=first['cost_per_rpc_interval_95']
        if bounds and all(r['cost_per_rpc_interval_95'] and bounds[1]<r['cost_per_rpc_interval_95'][0] for r in usable[1:]):
            preferred=first['channel']
    chosen=preferred if preferred and next(r['eligible'] for r in candidates if r['channel']==preferred) else None
    explanation=('Review '+chosen+' first using conservative historical cost/RPC comparison; confirm live operational facts. This is not an optimal treatment claim.' if chosen else
        'No ready channel recommendation: operational/policy prerequisites, sparse evidence or overlapping uncertainty prevent a supported choice. Descriptive comparison is for investigation only.')
    return candidates,chosen,explanation,comparison,preferred

def vulnerability_safeguard(con,case_id,as_of,when):
    """Approved case provenance only; no types, repayment scores or priority changes."""
    cutoff=min(when.astimezone(timezone.utc).replace(tzinfo=None),datetime.combine(as_of+timedelta(days=1),time()))
    cached=safe_records(con,"SELECT table_name FROM information_schema.tables WHERE table_catalog='temp' AND table_name='decision_safeguard_inputs'")
    if any(r.get('table_name')=='decision_safeguard_inputs' for r in cached):
        rows=safe_records(con,"SELECT DISTINCT recorded FROM decision_safeguard_inputs WHERE case_id=? AND extract_ts<=?",[case_id,cutoff])
    else:
        rows=safe_records(con,"""SELECT DISTINCT try_cast(r.vulnerable_customer_flag AS BOOLEAN) AS recorded
            FROM raw.collections_cases r JOIN restricted.case_records a
              ON r.case_id=a.case_id AND r.coll_customer_ref=a.source_key AND r.record_hash IS NOT DISTINCT FROM a.record_hash
            JOIN curated.cases c ON c.case_id=a.case_id AND c.golden_customer_id=a.golden_customer_id
            WHERE a.quality_reason IS NULL AND c.case_id=? AND try_cast(r.extract_ts AS TIMESTAMP)<=?""",[case_id,cutoff])
    values={r['recorded'] for r in rows if 'recorded' in r}
    state='recorded' if values=={True} else 'explicitly_not_recorded' if values=={False} else 'unknown_or_conflicting'
    return {'state':state,'certification_required':state!='explicitly_not_recorded',
        'source_cutoff_utc':cutoff.isoformat(),
        'source':'approved case matched to raw.collections_cases vulnerable_customer_flag',
        'scope':'Published current case snapshot and extract cutoff only; the flag has no historical availability timestamp. Mandatory support certification only, never repayment or priority ranking.'}


def staff_candidates(con,skills,language,blocked,certification_required=False):
    exclusions=Counter();agents=[]
    if blocked:return [],{'routing_blocked':1},blocked
    if language not in ('EN','FR'):return [],{'unknown_service_language':1},'Service language is unknown; employee routing review is required.'
    columns={r['column_name'] for r in safe_records(con,"SELECT column_name FROM information_schema.columns WHERE table_schema='raw' AND table_name='agents'")}
    missing_skills=[skill for skill in skills if skill not in columns]
    if missing_skills:return [],{'required_skill_schema_missing':len(missing_skills)},'Required roster skill evidence is unavailable: '+', '.join(missing_skills)+'. Supervisor review is required.'
    if certification_required and 'vulnerable_customer_certified' not in columns:
        return [],{'certification_evidence_unavailable':1},'Required vulnerable-customer certification evidence is unavailable; supervisor review is required.'
    if language=='FR' and 'site' not in columns:
        return [],{'french_site_evidence_unavailable':1},'French service requires the Montreal site under POL-COLL-001 section 5.5; site evidence is unavailable.'
    extras=(',site' if 'site' in columns else '')+(',vulnerable_customer_certified' if certification_required else '')
    roster=safe_records(con,'SELECT agent_id,status,languages,max_concurrent_cases,current_case_load,'+','.join(skills)+extras+' FROM raw.agents')
    if not roster:return [],{'roster_unavailable':1},'No usable staff roster is available.'
    grouped={}
    for row in roster:grouped.setdefault(row.get('agent_id'),[]).append(row)
    for agent_id,rows in grouped.items():
        if not agent_id or len({json.dumps(r,sort_keys=True,default=str) for r in rows})!=1:
            exclusions['missing_or_conflicting_agent_id']+=1;continue
        row=rows[0]
        if row['status']!='active':exclusions['inactive']+=1;continue
        try:
            languages=json.loads(row['languages']) if isinstance(row['languages'],str) else row['languages']
            if not isinstance(languages,list) or not all(isinstance(v,str) for v in languages):raise ValueError()
            capacity=int(row['max_concurrent_cases']);load=int(row['current_case_load'])
            values={skill:int(row[skill]) for skill in skills}
            if capacity<=0 or load<0 or any(not 0<=v<=5 for v in values.values()):raise ValueError()
        except (ValueError,TypeError,KeyError):exclusions['invalid_roster_fields']+=1;continue
        if language not in languages:exclusions['language_mismatch']+=1;continue
        if language=='FR':
            site=row.get('site')
            if not isinstance(site,str) or '\ufffd' in site:
                exclusions['unknown_or_corrupt_french_site']+=1;continue
            city=''.join(v for v in unicodedata.normalize('NFKD',site.strip().casefold()) if not unicodedata.combining(v))
            if city!='montreal':exclusions['french_service_site_mismatch']+=1;continue
        if certification_required and str(row.get('vulnerable_customer_certified')).lower()!='true':
            exclusions['required_certification_missing_or_unknown']+=1;continue
        if any(v<=0 for v in values.values()):exclusions['required_skill_missing']+=1;continue
        if load>=capacity:exclusions['capacity_full']+=1;continue
        agents.append({'agent_id':agent_id,'relevant_skill':values[skills[0]],'required_skill_values':values,
            'free_case_capacity':capacity-load,'capacity_utilization':load/capacity,
            'site':row.get('site'),'required_certification_satisfied':True if certification_required else None,
            'reason':'Active; matches '+language+' and every required skill; snapshot load below capacity.',
            'capacity_state':'snapshot only; live acceptance must be confirmed',
            'shift_site_availability':'Not validated; supervisor must confirm shift/site availability before reassignment.'})
    agents.sort(key=lambda r:(-min(r['required_skill_values'].values()),r['capacity_utilization'],-r['free_case_capacity'],r['agent_id']))
    return agents[:5],dict(exclusions),('Review staff matching all required needs; confirm current availability before reassignment.' if agents else
        'No eligible staff: inspect exclusion counts and use supervisor review. Do not relax language, skill or capacity requirements.')

def recommend(con,bundle,when):
    f,c,q=bundle['features'],bundle['case'],bundle['controls'];state=f['action_eligibility']
    gates={channel:contact_gate(bundle,channel,when) for channel in ('call','sms','email')}
    stale=any('snapshot_requires_refresh' in g['reasons'] for g in gates.values())
    if q.get('preferred_language') not in ('EN','FR'):
        for gate in gates.values():
            gate['eligible']=False;gate['reasons'].append('unknown_service_language')
    held=state.startswith('hold_') or state=='representative_review'
    hardship=f.get('hardship_mention') is True or c.get('hardship_flag') is True
    dispute=state=='dispute_review';dpd=f.get('case_max_dpd');skills=[];reasons=[];alternatives=[];missing=[]
    def reason(code,text,sources):reasons.append({'code':code,'reason':text,'sources':sources})
    if c.get('case_status')!='open':
        code='non_open_review';action='Review the non-open case record. Do not propose payment collection, outbound contact or new assignment.'
        reason(code,'Only open cases enter collection proposals. Status is '+str(c.get('case_status'))+'.',['case:'+c['case_id']])
    elif stale:
        code='refresh_required';action='Refresh current consent, holds, case facts and contact history before considering any customer action or routing.'
        reason(code,'The current-only release is stale at the supplied decision time.',['features:'+c['case_id']])
    elif held:
        code='hold_review';action='Specialist review of the active hold. Do not initiate outbound contact or request payment.'
        reason(code,state+' precedes treatment, channel and staff proposals.',['POL-COLL-001 §5.4, §7.3','features:'+c['case_id']])
    elif q.get('preferred_language') not in ('EN','FR'):
        code='language_review';action='Confirm the customer service language before payment discussion, outbound contact or staff assignment.'
        reason(code,'The service language is unknown; a compliant response cannot be selected.',['POL-COLL-001 §5.5'])
    elif dispute:
        code='dispute_review';action='Review the dispute and pause payment requests for the disputed amount until resolution.';skills=['skill_disputes']
        reason(code,'A dispute requires review before payment requests.',['PRC-COLL-012 §6.1','features:'+c['case_id']])
        if hardship:skills.append('skill_hardship');reason('competing_hardship_need','Hardship support is also required; route to staff meeting both needs.',['POL-COLL-004 §4.2'])
    elif hardship:
        code='hardship_review';action='Have a hardship specialist review and offer eligible support options before requesting payment.';skills=['skill_hardship']
        reason(code,'Recorded or extracted hardship is a support safeguard, not a repayment score.',['POL-COLL-004 §4.2-4.4','features:'+c['case_id']])
    elif f.get('open_ptp_days_to_due') is not None:
        code='existing_promise_review';action='Review the existing open promise and its due date before discussing another arrangement.'
        skills=['skill_late_stage' if dpd>90 else 'skill_mid_stage' if dpd>30 else 'skill_early_stage'] if dpd is not None else []
        reason(code,'An existing future-or-today promise is recorded; no new commitment is inferred.',['features:'+c['case_id']])
    elif f.get('callback_request') is True:
        code='callback_review';action='Confirm the requested callback date, service language and channel before considering another contact.'
        skills=['skill_late_stage' if dpd>90 else 'skill_mid_stage' if dpd>30 else 'skill_early_stage'] if dpd is not None else []
        reason(code,'A callback request is evidence to clarify, not authority to schedule or initiate contact.',['features:'+c['case_id'],'POL-COLL-001 §5.1-5.3'])
    else:
        code='case_preparation';action='Review verified account facts, contact restrictions and affordability with the customer before proposing an arrangement.'
        if dpd is not None:skills=['skill_late_stage' if dpd>90 else 'skill_mid_stage' if dpd>30 else 'skill_early_stage']
        reason(code,'No higher-priority hold, dispute, hardship or current promise was identified.',['features:'+c['case_id']])
    if skills and c.get('primary_product')=='auto_loan':
        skills.append('skill_auto_loans')
        reason('auto_loan_product_skill','The primary auto-loan product requires product expertise alongside stage or specialist needs.',['case:'+c['case_id'],'raw.agents skill_auto_loans'])
    elif c.get('primary_product') is None:
        missing.append('Primary product is unknown; additional product-specific routing needs cannot be determined.')
    paused=code in ('non_open_review','refresh_required','hold_review','language_review','dispute_review','hardship_review')
    if f.get('callback_request') is True:
        reason('callback_needs_confirmation','A callback signal exists; its date/channel must be clarified and cannot authorize contact.',['features:'+c['case_id']])
    if f.get('account_coverage')!='complete':missing.append('Account coverage is incomplete or unknown; verify amounts before assistance.')
    if f.get('hardship_mention') is None:missing.append('Text hardship evidence is unavailable; absence is not evidence of no hardship.')
    if dpd is None:missing.append('DPD is unknown; stage skill cannot be inferred.')
    if q.get('preferred_language') not in ('EN','FR'):missing.append('Service language is unknown.')
    alternatives.append({'action':'outbound_contact','status':'review_only' if any(g['eligible'] for g in gates.values()) else 'blocked',
        'reason':'Every channel requires its own current consent, time and restriction checks.'})
    alternatives.append({'action':'new_payment_arrangement','status':'paused' if paused else 'employee_review',
        'reason':'Higher-priority safeguards and existing commitments must be reviewed; no offer is executed.'})
    candidates,chosen,channel_text,comparison,preferred=channel_evidence(con,bundle,when,gates)
    if f.get('callback_request') is True:
        chosen=None
        channel_text+=' Confirm the unresolved customer callback date/channel first.'
        missing.append('Customer callback date/channel is unresolved; no contact time was inferred.')
    blocked=action if code in ('non_open_review','refresh_required','hold_review','language_review') else None
    safeguard=vulnerability_safeguard(con,c['case_id'],f['as_of_date'],when)
    if skills and safeguard['certification_required']:
        reason('support_certification_required','Recorded or unresolved vulnerability safeguard requires certified staff; assistance priority is unchanged.',['POL-COLL-004 section 4.5',safeguard['source']])
    if skills and q.get('preferred_language')=='FR':
        reason('french_site_required','French service staff must have verified Montreal site evidence.',['POL-COLL-001 section 5.5'])
    if safeguard['state']=='unknown_or_conflicting':missing.append('Vulnerability safeguard state is unknown or conflicting; certified staff are required pending clarification.')
    agents,excluded,routing_text=staff_candidates(con,skills,q.get('preferred_language'),blocked or ('Stage/specialist skill is unknown.' if not skills else None),safeguard['certification_required'])
    if chosen and not agents:
        chosen=None
        channel_text='No ready contact channel: qualified staff prerequisites are unresolved. Historical channel comparisons remain descriptive review evidence only.'
        missing.append('Qualified employee availability/certification/site must be confirmed before a contact proposal.')
    local=next((g.get('local_time') for g in gates.values() if g.get('local_time')),None)
    timing={'decision_local_time':local,'permitted_now':{ch:g['eligible'] for ch,g in gates.items()},
        'callback_confirmation_required':f.get('callback_request') is True,
        'customer_hours':{'start':str(q.get('permitted_start')),'end':str(q.get('permitted_end'))},
        'capacity_band_assumption':'Supplied time bands are compared with customer-local decision time; capacity timezone is not supplied and requires operational confirmation.',
        'reason':'Only the supplied decision time is checked. No future callback date or statistically best contact hour is inferred.',
        'scope':'Current snapshot only; unknown timezone/windows and stale dates fail closed.'}
    programmes=support_options(con,bundle) if code=='hardship_review' or (code=='dispute_review' and hardship) else []
    summary=action+' '+channel_text
    return {'case_id':c['case_id'],'summary':summary,'proposed_step':summary,'next_best_action':action,
        'channel_candidates':candidates,'suggested_channel':chosen,'routing_candidates':agents,'required_skill':skills[0] if skills else None,
        'support_options':programmes,
        'sources':list(dict.fromkeys(POLICY_SOURCES+['features:'+c['case_id'],'curated.contacts case-specific observed outcomes','raw.channel_capacity snapshot costs','raw.agents staff roster']+(['POL-COLL-004 section 4.5',safeguard['source']] if safeguard['certification_required'] else [])+(['POL-COLL-001 section 5.5'] if q.get('preferred_language')=='FR' else [])+[p['source'] for p in programmes])),
        'feature_version':f['definition_version'],'as_of_date':str(f['as_of_date']),'generator':'decision-rules-v0.3',
        'requires_human_review':True,'decision_time':when.isoformat(),'action_code':code,'decision_reasons':reasons,
        'alternatives':alternatives,'missing_evidence':missing,'payment_request_paused':paused,
        'review_priority':'safeguard_review_first' if paused else 'standard_case_review',
        'channel_explanation':channel_text,'comparison_order':comparison,
        'preferred_channel_pending_verification':preferred,'timing_review':timing,
        'routing_requirements':{'skills':skills,'language':q.get('preferred_language'),'competing_needs':dispute and hardship,
            'required_site':'Montreal' if q.get('preferred_language')=='FR' else None,'vulnerability_safeguard':safeguard},
        'routing_explanation':routing_text,'roster_exclusions':excluded,
        'explanation':'Policy safeguards precede treatment. Contact permission, internal review priority and staff review are separate. Channels need enough observed outcomes; staff must meet all required needs.',
        'limitations':['Channel cost/Wilson comparison is descriptive, not a trained or causal optimal treatment policy.',
            'Sparse/missing RPC outcomes do not support channel ranking. Wilson intervals do not cover selection bias or correlated contacts.',
            'Current case facts have no historical availability timestamps; this is not point-in-time treatment training.',
            'Capacity and costs are snapshots; live availability, customer preferences and program eligibility need confirmation.',
            'Protected customer attributes and accent are excluded from ranking; vulnerability only gates support certification, never repayment or priority. No contact, assignment or payment action executes.']}
