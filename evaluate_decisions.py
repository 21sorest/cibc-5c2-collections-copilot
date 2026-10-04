"""Audit prototype proposal safeguards on actual approved case records."""
from datetime import datetime,timezone
import json
import unicodedata

import duckdb
from assistant import load_case
from decisions import recommend
from pipeline import ROOT


PROJECTION_SQL="""CREATE TEMP TABLE decision_safeguard_inputs AS
            SELECT DISTINCT c.case_id,try_cast(r.vulnerable_customer_flag AS BOOLEAN) AS recorded,
                   try_cast(r.extract_ts AS TIMESTAMP) AS extract_ts
            FROM raw.collections_cases r JOIN restricted.case_records a
              ON r.case_id=a.case_id AND r.coll_customer_ref=a.source_key AND r.record_hash IS NOT DISTINCT FROM a.record_hash
            JOIN curated.cases c ON c.case_id=a.case_id AND c.golden_customer_id=a.golden_customer_id
            WHERE a.quality_reason IS NULL"""

def validate_projection(con,when):
    cases=con.execute("""SELECT case_id FROM raw.collections_cases r JOIN restricted.case_records a USING(case_id)
        JOIN curated.cases c USING(case_id) WHERE a.quality_reason IS NULL AND c.case_status='open'
        AND r.coll_customer_ref=a.source_key AND r.record_hash IS NOT DISTINCT FROM a.record_hash
        AND try_cast(r.extract_ts AS TIMESTAMP)<=?
        QUALIFY row_number() OVER(PARTITION BY try_cast(r.vulnerable_customer_flag AS BOOLEAN) ORDER BY sha256(case_id))=1""",[when.replace(tzinfo=None)]).fetchall()
    direct={case_id:recommend(con,load_case(con,case_id),when) for (case_id,) in cases}
    con.execute(PROJECTION_SQL)
    mismatches=[case_id for case_id,expected in direct.items() if recommend(con,load_case(con,case_id),when)!=expected]
    if mismatches:raise AssertionError('Direct/projected decision mismatch: '+', '.join(mismatches))
    return {'cases_checked':len(direct),'mismatches':0,'case_ids':list(direct)}


def evaluate():
    results=[]
    when=datetime(2026,9,28,15,tzinfo=timezone.utc)
    with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
        # Ephemeral approved projection avoids scanning the source CSV twice per audited case.
        # The database remains read-only; each evaluation gets a fresh connection and projection.
        projection_parity=validate_projection(con,when)
        cases=con.execute('''SELECT c.case_id FROM curated.cases c JOIN features.case_current f USING(case_id)
            QUALIFY row_number() OVER (PARTITION BY c.case_status,f.action_eligibility,
                coalesce(f.hardship_mention,false) OR coalesce(c.hardship_flag,false),
                (SELECT bool_or(recorded) FROM decision_safeguard_inputs s WHERE s.case_id=c.case_id AND s.extract_ts<=TIMESTAMP '2026-09-28 15:00:00')
                ORDER BY sha256(c.case_id))<=5
            ORDER BY c.case_status,f.action_eligibility,c.case_id''').fetchall()
        for (case_id,) in cases:
            bundle=load_case(con,case_id)
            proposal=recommend(con,bundle,when)
            failures=[]
            selected=proposal['suggested_channel']
            if selected and not proposal['routing_candidates']:
                failures.append('ready contact channel lacks staff meeting mandatory support/site requirements')
            if selected and bundle['case']['case_status']!='open':
                failures.append('non-open case has a selected outbound channel')
            if selected and bundle['controls'].get('consent_'+selected) is not True:
                failures.append('selected channel lacks explicit servicing consent')
            if selected=='call' and bundle['controls'].get('do_not_call') is not False:
                failures.append('call selected with a do-not-call or unknown state')
            if bundle['features']['action_eligibility'].startswith('hold_') and (selected or proposal['routing_candidates']):
                failures.append('active hold produced contact or staff assignment candidates')
            if bundle['case']['case_status']!='open' and (proposal['routing_candidates'] or not proposal['payment_request_paused']):
                failures.append('non-open case produced assignment candidates or payment discussion')
            for candidate in proposal['channel_candidates']:
                if candidate['eligible'] and not candidate['capacity_evidence']:
                    failures.append('operationally eligible channel lacks current band/capacity evidence')
            if selected and next(r for r in proposal['channel_candidates'] if r['channel']==selected)['known_rpc_count']<20:
                failures.append('selected channel relies on sparse outcomes')
            if proposal['action_code']=='dispute_review' and not proposal['payment_request_paused']:
                failures.append('dispute did not pause payment requests')
            for agent in proposal['routing_candidates']:
                if any(v<=0 for v in agent['required_skill_values'].values()):
                    failures.append('staff candidate does not meet every required specialist need')
                status,languages,capacity,load,site,certified=con.execute('SELECT status,languages,try_cast(max_concurrent_cases AS INTEGER),try_cast(current_case_load AS INTEGER),site,try_cast(vulnerable_customer_certified AS BOOLEAN) FROM raw.agents WHERE agent_id=?',[agent['agent_id']]).fetchone()
                if status!='active' or not capacity>load or bundle['controls']['preferred_language'] not in json.loads(languages):
                    failures.append('staff candidate violates active/language/capacity requirement')
                if bundle['controls']['preferred_language']=='FR':
                    city=''.join(v for v in unicodedata.normalize('NFKD',str(site).strip().casefold()) if not unicodedata.combining(v))
                    if city!='montreal':failures.append('French routing candidate lacks verified Montreal site')
                if proposal['routing_requirements']['vulnerability_safeguard']['certification_required'] and certified is not True:
                    failures.append('staff candidate lacks mandatory support certification')
            current=recommend(con,bundle,datetime.now(timezone.utc))
            if current['routing_candidates']:
                failures.append('current-time routing proposed from stale snapshot')
            if current['suggested_channel']:
                failures.append('current-time contact selected from stale snapshot')
            results.append({'case_id':case_id,'status':bundle['case']['case_status'],'selected_snapshot_channel':selected,
                'routing_candidates':len(proposal['routing_candidates']),'action_code':proposal['action_code'],
                'vulnerability_safeguard':proposal['routing_requirements']['vulnerability_safeguard']['state'],
                'roster_exclusions':proposal['roster_exclusions'],
                'comparison_channels':len(proposal['comparison_order']),'failures':failures})
    report={'generator':'decision-rules-v0.3','samples':len(results),'projection_parity':projection_parity,'failed_cases':sum(bool(r['failures']) for r in results),'results':results,
        'scope':'Up to five approved cases per status, safeguard state, financial-hardship and recorded-vulnerability safeguard stratum, ordered by hashed case ID. Snapshot simulation and current-time stale-data checks.',
        'limitations':['Safeguard audit only; not a gold evaluation of optimal action, channel success, routing quality or business benefit.',
            'Capacity is a supplied snapshot. No contact, assignment or payment action was executed.']}
    (ROOT/'reports/decision_safeguards.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
    if report['failed_cases']:
        raise SystemExit(1)


if __name__=='__main__':
    evaluate()
