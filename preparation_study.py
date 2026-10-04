"""Prepare a counterbalanced human study and analyze actual participant observations."""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median

import duckdb
from pipeline import ROOT

FIELDS=['participant','pair_id','mode','case_id','order','elapsed_seconds','correct_items','total_items','unsafe_accepted']


def assignments(manifest):
    participants=manifest['participants'];pairs=manifest['pairs']
    if len(participants)!=2 or len(set(participants))!=2 or len(pairs)!=4:
        raise ValueError('This protocol needs two distinct participants and four pairs.')
    if len({p['pair_id'] for p in pairs})!=4 or any(len(p['cases'])!=2 for p in pairs):
        raise ValueError('Each pair needs a unique code and two cases.')
    cases=[case for pair in pairs for case in pair['cases']]
    if len({c['case_id'] for c in cases})!=8 or len({c['golden_customer_id'] for c in cases})!=8:
        raise ValueError('Matched study cases must represent eight distinct customers.')
    rows=[]
    for participant_index,participant in enumerate(manifest['participants']):
        order=0
        for pair_index,pair in enumerate(manifest['pairs']):
            manual=pair['cases'][participant_index%2]['case_id']
            assisted=pair['cases'][1-participant_index%2]['case_id']
            modes=['manual','assisted'] if (participant_index+pair_index)%2==0 else ['assisted','manual']
            for mode in modes:
                order+=1
                rows.append({'participant':participant,'pair_id':pair['pair_id'],'mode':mode,
                    'case_id':manual if mode=='manual' else assisted,'order':order,
                    'elapsed_seconds':'','correct_items':'','total_items':6,'unsafe_accepted':''})
    return rows


def prepare(database,output):
    output=Path(output)
    if (output/'results.csv').exists():
        raise FileExistsError('Study results already exist. Use a new output directory to preserve observations.')
    with duckdb.connect(str(database),read_only=True) as con:
        cursor=con.execute("""SELECT case_id,golden_customer_id,queue,current_bucket,total_overdue_cad,current_dpd
            FROM curated.cases WHERE case_status='open'
            QUALIFY row_number() OVER(PARTITION BY queue,current_bucket ORDER BY sha256(case_id))<=100
            ORDER BY queue,current_bucket,total_overdue_cad,case_id""")
        candidates=[dict(zip([c[0] for c in cursor.description],row)) for row in cursor.fetchall()]
    edges=[]
    for left,right in zip(candidates,candidates[1:]):
        if (left['queue'],left['current_bucket'])!=(right['queue'],right['current_bucket']):
            continue
        if left['golden_customer_id']==right['golden_customer_id']:
            continue
        a,b=float(left['total_overdue_cad']),float(right['total_overdue_cad'])
        distance=abs(a-b)/max(a,b,1)+abs(left['current_dpd']-right['current_dpd'])/100
        edges.append((distance,left['case_id'],right['case_id'],left,right))
    pairs=[]
    used=set()
    for distance,_,__,left,right in sorted(edges):
        customers={left['golden_customer_id'],right['golden_customer_id']}
        if customers&used:
            continue
        used|=customers
        pairs.append({'pair_id':'PAIR-'+str(len(pairs)+1),'matching_distance':round(distance,6),'cases':[left,right]})
        if len(pairs)==4:
            break
    if len(pairs)!=4:
        raise ValueError('Eight distinct approved open-case customers could not be paired.')
    manifest={'source':'curated.cases, approved current snapshot','as_of_date':'2026-09-28',
        'created_at':datetime.now(timezone.utc).isoformat(),'participants':['P01','P02'],'pairs':pairs,
        'matching':'Same queue/bucket; adjacent overdue amounts, ranked by relative overdue and DPD difference.',
        'limitations':['Purposefully matched synthetic cases, not a random population sample.',
            'Participants must provide real observations. Preparation creates no study results.']}
    output.mkdir(parents=True,exist_ok=True)
    (output/'case_pairs.json').write_text(json.dumps(manifest,indent=2,default=str),encoding='utf-8')
    with (output/'results.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(assignments(manifest))
    (output/'instructions.md').write_text("""# Human preparation study

A neutral facilitator first reviews the matched pairs. Keep case_pairs.json facilitator-only because it contains matching financial fields; participants receive only their assigned case IDs from results.csv. Use the supplied participant order. Each participant sees each case once. Keep participants' answers independent. Manual mode uses source records and policy documents; assisted mode uses the app. Include loading and correction time.

For each assigned case, submit six items: overdue amount, DPD, open promise status/due date, contact restrictions, hardship evidence, and applicable support/contact policy. A neutral facilitator checks each item against source evidence before entering correct_items from 0 to 6. Enter measured elapsed_seconds and unsafe_accepted as true or false. Do not invent missing observations.

Record no participant names. See docs/preparation_study.md for study design and limitations. Run preparation_study.py analyze only after all 16 tasks are completed. The sheet's case/mode/order assignments must remain unchanged.
""",encoding='utf-8')
    return {'pairs':4,'participants':2,'blank_rows':16,'output':str(output)}


def analyze_rows(manifest,observations):
    expected=assignments(manifest)
    keys=lambda r:(r['participant'],r['pair_id'],r['mode'])
    target={keys(r):r for r in expected}
    if len(target)!=len(expected) or len(observations)!=len(expected):
        raise ValueError('Study requires every assigned task exactly once; incomplete pairs are invalid.')
    seen=set();participant_cases=set();clean=[]
    for row in observations:
        key=keys(row)
        if key in seen or key not in target:
            raise ValueError('Duplicate or unassigned participant/pair/mode task.')
        seen.add(key)
        assignment=target[key]
        if row['case_id']!=assignment['case_id'] or str(row['order'])!=str(assignment['order']):
            raise ValueError('Case/mode/order changed; the counterbalanced study is confounded.')
        case_key=(row['participant'],row['case_id'])
        if case_key in participant_cases:
            raise ValueError('A participant cannot reuse the same case.')
        participant_cases.add(case_key)
        try:
            seconds=float(row['elapsed_seconds'])
            correct=int(row['correct_items']);total=int(row['total_items'])
        except (ValueError,TypeError):
            raise ValueError('Actual human timing and item scores are required.') from None
        if not math.isfinite(seconds) or seconds<=0 or total!=6 or not 0<=correct<=total:
            raise ValueError('Timings must be finite/positive, with six valid item scores.')
        unsafe=str(row['unsafe_accepted']).strip().lower()
        if unsafe not in ('true','false'):
            raise ValueError('unsafe_accepted requires an observed true or false value.')
        clean.append({**row,'seconds':seconds,'correct':correct,'total':total,'unsafe':unsafe=='true'})
    if seen!=set(target):
        raise ValueError('Missing assigned study tasks.')
    modes={}
    for mode in ('manual','assisted'):
        tasks=[r for r in clean if r['mode']==mode]
        complete=[r for r in tasks if r['correct']==r['total'] and not r['unsafe']]
        modes[mode]={'tasks':len(tasks),'all_task_median_seconds':median(r['seconds'] for r in tasks),
            'correct_complete_tasks':len(complete),
            'correct_complete_median_seconds':median(r['seconds'] for r in complete) if complete else None,
            'incorrect_items':sum(r['total']-r['correct'] for r in tasks),
            'unsafe_accepted_tasks':sum(r['unsafe'] for r in tasks)}
    def improvement(field):
        a,b=modes['manual'][field],modes['assisted'][field]
        return 100*(a-b)/a if a is not None and b is not None else None
    paired=[]
    for participant,pair in sorted({(r['participant'],r['pair_id']) for r in clean}):
        task={r['mode']:r for r in clean if r['participant']==participant and r['pair_id']==pair}
        paired.append(100*(task['manual']['seconds']-task['assisted']['seconds'])/task['manual']['seconds'])
    return {'participants':len(manifest['participants']),'matched_pairs':len(manifest['pairs']),
        'tasks':len(clean),'paired_comparisons':len(paired),'modes':modes,
        'all_task_median_improvement_pct':improvement('all_task_median_seconds'),
        'correct_complete_median_improvement_pct':improvement('correct_complete_median_seconds'),
        'median_within_participant_pair_improvement_pct':median(paired),
        'correct_complete_definition':'All six items correct and no unsafe suggestion accepted.',
        'limitations':['Exploratory matched-case human study; small sample, not bank-wide savings evidence.',
            'Correct-complete filtering can change case composition; report all-task timing and errors alongside it.',
            'Timings and scores are facilitator-entered observations, not independently authenticated.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','analyze'])
    parser.add_argument('--database',type=Path,default=ROOT/'data/collections.duckdb')
    parser.add_argument('--directory',type=Path,default=ROOT/'data/study')
    args=parser.parse_args()
    try:
        if args.command=='prepare':
            result=prepare(args.database,args.directory)
        else:
            manifest=json.loads((args.directory/'case_pairs.json').read_text(encoding='utf-8'))
            with (args.directory/'results.csv').open(encoding='utf-8',newline='') as handle:
                result=analyze_rows(manifest,list(csv.DictReader(handle)))
            (args.directory/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
    except (ValueError,FileExistsError,FileNotFoundError) as error:
        parser.error(str(error))
