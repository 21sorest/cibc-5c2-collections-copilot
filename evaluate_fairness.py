"""Protected fields are used only for aggregate development auditing, never scoring."""
import json
from collections import defaultdict

import duckdb
from pipeline import ROOT
from train_classifier import MODEL, labeled_rows, metrics, predict


def evaluate():
    model=json.loads(MODEL.read_text(encoding='utf-8'))
    rows,_=labeled_rows()
    evaluation_ids=set(model['evaluation_ids'])
    holdout=[row for row in rows if row['id'] in evaluation_ids]
    if len(holdout)!=len(evaluation_ids):
        raise ValueError('Evaluation source coverage changed; retrain before this audit')
    customers=sorted({row['customer'] for row in holdout})
    with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
        groups=con.execute("""SELECT m.golden_customer_id,
            CASE WHEN count(DISTINCT nullif(c.gender_code,''))=1 THEN max(c.gender_code) ELSE 'unknown_or_conflicting' END,
            CASE WHEN count(DISTINCT nullif(c.citizenship_status,''))=1 THEN max(c.citizenship_status) ELSE 'unknown_or_conflicting' END
            FROM restricted.identity_map m JOIN raw.customers c ON m.source_key=c.crm_customer_id
            WHERE m.source_system='crm' AND m.status='accepted' AND m.golden_customer_id IN (SELECT unnest(?)) GROUP BY 1""",[customers]).fetchall()
    attributes={row[0]:row[1:] for row in groups}
    slices={}
    for index,name in enumerate(('gender_code','citizenship_status')):
        buckets=defaultdict(list)
        for row in holdout:
            buckets[attributes.get(row['customer'],('unknown','unknown'))[index]].append(row)
        slices[name]={}
        for group,examples in sorted(buckets.items()):
            positives=sum(row['labels']['hardship'] for row in examples)
            if len(examples)<10 or positives<10:
                slices[name][group]={'examples':len(examples),'hardship_positives':positives,'metrics_suppressed':'Insufficient support to interpret precision/recall'}
            else:
                score=metrics(examples,lambda text:{k:v['flag'] for k,v in predict(text,model).items()})['hardship']
                slices[name][group]={'examples':len(examples),'hardship_positives':positives,'hardship_metrics':score}
    probes={}
    for prefix in ('I am a woman. ','I am a man. ','I am Canadian. ','I am a newcomer. '):
        changes=sum(predict(row['text'],model)['hardship']['flag']!=predict(prefix+row['text'],model)['hardship']['flag'] for row in holdout)
        probes[prefix.strip()]={'examples':len(holdout),'hardship_flag_changes':changes}
    report={'scope':'Aggregate public development audit, not a fairness certification','evaluation_rows':len(holdout),
        'protected_attribute_use':'Read only in this audit. Neither classifier inputs nor decision/routing code receive these attributes.',
        'hardship_slices':slices,'counterfactual_prefix_probes':probes,
        'limitations':['Small public evaluation partition; repeated customer groups are correlated.',
            'Low-support slices are suppressed. Observed differences do not establish discriminatory behavior or statistical parity.',
            'Text can contain proxies even when direct protected fields are excluded. Prefix invariance alone does not prove fairness.',
            'Hardship is a support safeguard, not repayment ranking; all model output remains subject to employee review.']}
    (ROOT/'reports/classifier_fairness.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    evaluate()
