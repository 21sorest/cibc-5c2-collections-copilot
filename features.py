"""Materialize the same feature definition that the live case reader serves."""
import argparse
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import time

import duckdb
from pipeline import ROOT, DEFAULT_RELEASE
from text_signals import VERSION, extract

FEATURE_NAMES = ['case_max_dpd','case_overdue_cad','days_since_payment','broken_ptp_90d',
 'kept_ptp_rate_90d','open_ptp_days_to_due','salary_decline_ratio','contact_attempts_7d',
 'channel_rpc_rate_90d','hardship_mention','callback_request','action_eligibility']


def safe_file(release, relative):
    base = (Path(release) / 'files').resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise ValueError('Source file leaves the release directory')
    return target


def materialize(database=ROOT/'data/collections.duckdb', release=DEFAULT_RELEASE):
    start = time.monotonic()
    sql = (ROOT/'sql/features.sql').read_text(encoding='utf-8')
    with duckdb.connect(str(database)) as con:
        dates = con.execute('SELECT DISTINCT as_of_date FROM golden.c360').fetchall()
        if dates != [(date(2026,9,28),)]:
            raise ValueError('Only the supplied 2026-09-28 current snapshot is supported')
        con.execute("SET memory_limit='4GB'")
        con.execute('SET threads=4')
        con.execute('BEGIN')
        try:
            con.execute('CREATE SCHEMA IF NOT EXISTS features')
            con.execute('CREATE OR REPLACE TABLE features.text_evidence(source_id VARCHAR,kind VARCHAR,case_id VARCHAR,event_date DATE,hardship BOOLEAN,callback BOOLEAN,cease BOOLEAN,insolvency BOOLEAN,dispute BOOLEAN,extractor_version VARCHAR)')
            print('Extracting note signals...', flush=True)
            reader = con.cursor()
            reader.execute('SELECT note_id,case_id,cast(note_ts_utc AS DATE),note_text FROM restricted.note_records WHERE quality_reason IS NULL')
            while batch := reader.fetchmany(10000):
                rows = [(key,'note',case,event,*extract(text).values(),VERSION) for key,case,event,text in batch]
                # Native relation insertion avoids hundreds of thousands of individual SQL writes.
                con.execute('INSERT INTO features.text_evidence SELECT unnest($1),\'note\',unnest($2),unnest($3),unnest($4),unnest($5),unnest($6),unnest($7),unnest($8),$9',
                    [[r[i] for r in rows] for i in (0,2,3,4,5,6,7,8)]+[VERSION])
            print('Extracting customer transcript signals...', flush=True)
            calls = con.execute("SELECT t.transcript_id,t.case_id,try_cast(t.call_start_ts AS DATE),t.file_path FROM curated.transcripts t WHERE try_cast(t.call_start_ts AS DATE)<=DATE '2026-09-28'").fetchall()
            rows=[]
            for key,case,event,path in calls:
                body=json.loads(safe_file(release,path).read_text(encoding='utf-8'))
                text=' '.join(t['text'] for t in body['turns'] if t['speaker']=='customer')
                rows.append((key,'transcript',case,event,*extract(text).values(),VERSION))
            if rows:
                con.execute('INSERT INTO features.text_evidence SELECT unnest($1),\'transcript\',unnest($2),unnest($3),unnest($4),unnest($5),unnest($6),unnest($7),unnest($8),$9',
                    [[r[i] for r in rows] for i in (0,2,3,4,5,6,7,8)]+[VERSION])
            con.execute("SET VARIABLE feature_date=DATE '2026-09-28'")
            print('Materializing the 12 case features...', flush=True)
            con.execute(sql)
            count=con.execute('SELECT count(*) FROM features.case_current').fetchone()[0]
            assert count == con.execute('SELECT count(*) FROM curated.cases').fetchone()[0]
            assert con.execute('SELECT count(*)-count(DISTINCT case_id) FROM features.case_current').fetchone()[0] == 0
            assert con.execute('SELECT count(*) FROM features.case_current WHERE kept_ptp_rate_90d NOT BETWEEN 0 AND 1 OR days_since_payment<0 OR broken_ptp_90d<0').fetchone()[0] == 0
            sample=con.execute('SELECT case_id FROM features.case_current ORDER BY case_id LIMIT 100').fetchall()
            # The online reader is deliberately the persisted, versioned materialization.
            for (case,) in sample:
                offline=con.execute('SELECT * FROM features.case_current WHERE case_id=?',[case]).fetchone()
                assert tuple(read_case(con,case).values()) == offline
            summary={'as_of_date':'2026-09-28','definition_version':'features-v0.5','sql_sha256':hashlib.sha256(sql.encode()).hexdigest(),
                'cases':count,'features':FEATURE_NAMES,'extractor':VERSION,'parity_sample':len(sample),
                'eligibility_counts':con.execute('SELECT action_eligibility,count(*) FROM features.case_current GROUP BY 1 ORDER BY 1').fetchall(),
                'missing_salary_ratio':con.execute('SELECT count(*) FROM features.case_current WHERE salary_decline_ratio IS NULL').fetchone()[0],
                'duration_seconds':round(time.monotonic()-start,2)}
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
    (ROOT/'reports/features_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)
    return summary


def read_case(con, case_id):
    cursor=con.execute('SELECT * FROM features.case_current WHERE case_id=?',[case_id])
    row=cursor.fetchone()
    if row is None:
        raise ValueError('Unknown or quarantined case')
    return dict(zip([c[0] for c in cursor.description],row))


def evaluate(release=DEFAULT_RELEASE, database=ROOT/'data/collections.duckdb'):
    with duckdb.connect(str(database),read_only=True) as con:
        metrics={key:dict(tp=0,fp=0,fn=0,tn=0) for key in ['hardship','cease','insolvency','dispute']}
        labels=list(csv.DictReader((Path(release)/'labels/agent_notes_labels_public_500.csv').open(encoding='utf-8')))
        notes=dict(con.execute('SELECT note_id,note_text FROM restricted.note_records WHERE quality_reason IS NULL AND note_id IN (SELECT unnest($1))',[[row['note_id'] for row in labels]]).fetchall())
        found=0
        for label in labels:
            note=notes.get(label['note_id'])
            if note is None:
                continue
            found+=1
            predicted=extract(note)
            for key in metrics:
                column={'hardship':'label_hardship','cease':'label_cease_request','insolvency':'label_insolvency_mention','dispute':'label_dispute'}[key]
                actual=label[column] in ('true','clear','possible')
                metrics[key]['tp' if actual and predicted[key] else 'fn' if actual else 'fp' if predicted[key] else 'tn']+=1
        for value in metrics.values():
            value['precision']=value['tp']/(value['tp']+value['fp']) if value['tp']+value['fp'] else None
            value['recall']=value['tp']/(value['tp']+value['fn']) if value['tp']+value['fn'] else None
        report={'extractor':VERSION,'dataset':'public notes labels, development evaluation, not held-out','label_rows':len(labels),'evaluated':found,'metrics':metrics}
        call_labels=list(csv.DictReader((Path(release)/'labels/call_transcripts_labels_public_500.csv').open(encoding='utf-8')))
        paths=dict(con.execute('SELECT transcript_id,file_path FROM curated.transcripts WHERE transcript_id IN (SELECT unnest(?))',[[r['transcript_id'] for r in call_labels]]).fetchall())
        call_metrics={key:dict(tp=0,fp=0,fn=0,tn=0) for key in metrics}
        holdout_metrics={key:dict(tp=0,fp=0,fn=0,tn=0) for key in metrics}
        holdout_count=0
        call_count=0
        for label in call_labels:
            path=paths.get(label['transcript_id'])
            if path is None:
                continue
            body=json.loads(safe_file(release,path).read_text(encoding='utf-8'))
            text=' '.join(t['text'] for t in body['turns'] if t['speaker']=='customer')
            predicted=extract(text)
            call_count+=1
            holdout=int(label['transcript_id'])%5==0
            holdout_count+=int(holdout)
            for key in call_metrics:
                column={'hardship':'label_hardship','cease':'label_cease_request','insolvency':'label_insolvency_mention','dispute':'label_dispute'}[key]
                actual=label[column] in ('true','clear','possible')
                call_metrics[key]['tp' if actual and predicted[key] else 'fn' if actual else 'fp' if predicted[key] else 'tn']+=1
                if holdout:
                    holdout_metrics[key]['tp' if actual and predicted[key] else 'fn' if actual else 'fp' if predicted[key] else 'tn']+=1
        for value in call_metrics.values():
            value['precision']=value['tp']/(value['tp']+value['fp']) if value['tp']+value['fp'] else None
            value['recall']=value['tp']/(value['tp']+value['fn']) if value['tp']+value['fn'] else None
        report['transcripts']={'label_rows':len(call_labels),'evaluated':call_count,'metrics':call_metrics,
            'scope':'public transcript development labels, customer turns only; not a hidden test'}
        for value in holdout_metrics.values():
            value['precision']=value['tp']/(value['tp']+value['fp']) if value['tp']+value['fp'] else None
            value['recall']=value['tp']/(value['tp']+value['fn']) if value['tp']+value['fn'] else None
        report['transcript_holdout']={'selection':'public transcript_id modulo 5 equals 0; examples excluded from transcript rule tuning',
            'evaluated':holdout_count,'metrics':holdout_metrics,
            'limitation':'The original public-label aggregate metrics were inspected before partitioning. This is a development hold-out, not a blind or organizer-held-out test.'}
        (ROOT/'reports/text_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build','evaluate'])
    args=parser.parse_args()
    materialize() if args.command=='build' else evaluate()

