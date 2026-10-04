"""Measure local draft validation and latency; does not claim semantic correctness."""
from datetime import datetime, timezone
import json
import statistics

import duckdb
from assistant import draft_brief, load_case
from local_llm import enhance_summary
from pipeline import ROOT


def evaluate(limit=10):
    results=[]
    with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
        cases=con.execute("SELECT case_id FROM curated.cases WHERE case_status='open' ORDER BY case_id DESC LIMIT ?",[limit]).fetchall()
        for (case,) in cases:
            bundle=load_case(con,case)
            brief=draft_brief(bundle,'call',datetime(2026,9,28,15,tzinfo=timezone.utc))
            try:
                result=enhance_summary(bundle,brief)
                assert result['contact_gate']==brief['contact_gate'] and result['proposed_step']==brief['proposed_step']
                row={'case_id':case,'validation_passed':True,'summary':result['summary'],'metadata':result['ai_metadata']}
            except ValueError as error:
                row={'case_id':case,'validation_passed':False,'error':str(error)}
            results.append(row)
            print(json.dumps(row),flush=True)
    latencies=[r['metadata']['latency_seconds'] for r in results if r['validation_passed']]
    report={'samples':len(results),'validation_passed':len(latencies),'validation_failed':len(results)-len(latencies),
        'median_latency_seconds':statistics.median(latencies) if latencies else None,'results':results,
        'limitations':['Typed source/field/value equality validates selected facts; it does not establish summary completeness.',
            'Deterministically selected current cases, not a blind benchmark. Human summary evaluation remains pending.',
            'Small pretrained CPU language model, not trained by the team. The separate classifier is locally trained.',
            'Free-form model text is rejected. Only verified source fields enter deterministic sentences. This is development, not blind evaluation.']}
    (ROOT/'reports/local_llm_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    evaluate()
