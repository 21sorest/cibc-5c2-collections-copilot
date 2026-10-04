"""Compare supported numeric development answers, never load hidden test answers."""
import csv
import io
import json
import re

import duckdb
from pipeline import ROOT,DEFAULT_RELEASE
from questions import answer


def table(text):
    rows=list(csv.DictReader(io.StringIO(text.strip())))
    return rows if rows and all(None not in row for row in rows) else None


def compare_tables(actual,gold,tolerance):
    expected=table(gold)
    received=table(actual)
    if not expected or not received:
        return {'status':'not_automatically_scored'}
    if len(expected)!=len(received):
        return {'status':'failed','reason':'different number of groups','expected':len(expected),'actual':len(received)}
    fields=list(expected[0])
    if not all(field in received[0] for field in fields):
        return {'status':'failed','reason':'missing expected result columns','fields':fields}
    differences=[]
    for left,right in zip(expected,received):
        for field in fields:
            try:
                a,b=float(left[field]),float(right[field])
                if abs(a-b)>tolerance:
                    differences.append({'field':field,'expected':a,'actual':b})
            except (ValueError,TypeError):
                if left[field]!=right[field]:
                    differences.append({'field':field,'expected':left[field],'actual':right[field]})
    return {'status':'failed' if differences else 'passed','differences':differences}


def evaluate():
    labels=list(csv.DictReader((DEFAULT_RELEASE/'labels/benchmark_dev_answers.csv').open(encoding='utf-8')))
    with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
        questions={r[0]:r[1:] for r in con.execute("SELECT question_id,question_text,tolerance FROM raw.benchmark_questions WHERE split='dev'").fetchall()}
        results=[]
        for row in labels:
            question,tolerance=questions[row['question_id']]
            result=answer(con,question)
            if not row['gold_sql_reference']:
                check={'status':'requires_semantic_review','refused':result['refused']}
            elif result['refused']:
                check={'status':'failed','reason':'supported data question refused'}
            else:
                number=re.search(r'\d+(?:\.\d+)?',tolerance or '')
                threshold=float(number[0]) if number else 0
                check=compare_tables(result['answer'],row['gold_answer'],threshold)
            results.append({'question_id':row['question_id'],**check})
    summary={'scope':'public development answers only; numeric table checks; document/refusal/transcript answers require semantic review',
        'results':results,'passed':sum(r['status']=='passed' for r in results),
        'failed':sum(r['status']=='failed' for r in results)}
    (ROOT/'reports/benchmark_dev_evaluation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    evaluate()
