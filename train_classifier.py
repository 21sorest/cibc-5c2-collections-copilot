"""Reproducible CPU text classifier, with customer/duplicate-grouped development splits."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import time

import duckdb
from features import safe_file
from pipeline import ROOT, DEFAULT_RELEASE
from text_signals import VERSION, extract, has_negated_signal, normalize, redact

MODEL = ROOT/'data/models/text_classifier.json'
SIGNALS = {'hardship':'label_hardship','dispute':'label_dispute',
           'cease':'label_cease_request','insolvency':'label_insolvency_mention'}


def tokens(text):
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", normalize(redact(text)))
    return set(words + [a+' '+b for a,b in zip(words,words[1:])])


def fit(rows):
    vocabulary = Counter(term for row in rows for term in tokens(row['text']))
    vocabulary = {word for word,count in vocabulary.items() if count>=2}
    models = {}
    for signal in SIGNALS:
        classes = [[row for row in rows if row['labels'][signal]==flag] for flag in (False,True)]
        if any(not group for group in classes):
            models[signal] = {'supported':False}
            continue
        counts = [Counter(term for row in group for term in tokens(row['text']) if term in vocabulary) for group in classes]
        totals = [sum(count.values())+len(vocabulary) for count in counts]
        models[signal] = {'supported':True,'bias':math.log(len(classes[1])/len(classes[0])),
            'weights':{term:math.log((counts[1][term]+1)/totals[1])-math.log((counts[0][term]+1)/totals[0]) for term in sorted(vocabulary)},
            'training_positive':len(classes[1]),'training_negative':len(classes[0])}
    return {'version':'multinomial-nb-v0.1','models':models,
        'tokenization':'redacted normalized unique word and adjacent word-pair occurrences; minimum training document frequency 2',
        'limitation':'Uncalibrated model scores, not probabilities of legal or financial status. Human review required.'}


def predict(text, model):
    terms=tokens(text)
    result={}
    for signal,weights in model['models'].items():
        if not weights['supported']:
            result[signal]={'flag':None,'score':None}
            continue
        value=weights['bias']+sum(weights['weights'].get(term,0) for term in terms)
        score=1/(1+math.exp(-max(-700,min(700,value))))
        result[signal]={'flag':value>=0,'score':round(score,6)}
    return result


def review_signals(text,predictions,rules=None):
    """One live/evaluation definition; trained scores are review cues, not calibrated probabilities."""
    result=dict(extract(text) if rules is None else rules)
    score=predictions.get('hardship',{}).get('score')
    denial=has_negated_signal(text,'hardship') or bool(re.search(r'\b(?:i|we) (?:can|am able to|are able to) afford\b',normalize(text)))
    result['hardship']=result['hardship'] or (score is not None and score>=0.95 and not denial)
    return result


def labeled_rows(release=DEFAULT_RELEASE, database=ROOT/'data/collections.duckdb'):
    rows=[]
    missing=[]
    with duckdb.connect(str(database),read_only=True) as con:
        for kind,name,key in [('note','agent_notes_labels_public_500.csv','note_id'),('transcript','call_transcripts_labels_public_500.csv','transcript_id')]:
            with (Path(release)/'labels'/name).open(encoding='utf-8') as handle:
                labels=list(csv.DictReader(handle))
            ids=[row[key] for row in labels]
            if kind=='note':
                sources={row[0]:row[1:] for row in con.execute('SELECT n.note_id,n.note_text,c.golden_customer_id FROM restricted.note_records n JOIN curated.cases c USING(case_id) WHERE n.quality_reason IS NULL AND n.note_id IN (SELECT unnest(?))',[ids]).fetchall()}
            else:
                sources={row[0]:row[1:] for row in con.execute("SELECT transcript_id,file_path,golden_customer_id FROM curated.transcripts WHERE transcript_id IN (SELECT unnest(?))",[ids]).fetchall()}
            for label in labels:
                if label.get('label_protected_attribute_mentioned')=='true':
                    missing.append(kind+':'+label[key]+':protected_content_excluded')
                    continue
                source=sources.get(label[key])
                if source is None:
                    missing.append(kind+':'+label[key])
                    continue
                text,customer=source
                if kind=='transcript':
                    body=json.loads(safe_file(release,text).read_text(encoding='utf-8'))
                    text=' '.join(turn['text'] for turn in body['turns'] if turn['speaker']=='customer')
                rows.append({'id':kind+':'+label[key],'kind':kind,'customer':customer,'text':text,
                    'labels':{signal:label[column] in ('true','clear','possible') for signal,column in SIGNALS.items()}})
    return rows,missing


def grouped_split(rows):
    # Connected groups prevent customer, normalized-text and actual token-input overlap.
    parent=list(range(len(rows)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    seen={}
    for i,row in enumerate(rows):
        for key in (('customer',row['customer']),('text',normalize(redact(row['text']))),
                    ('tokens',tuple(sorted(tokens(row['text']))))):
            if key in seen:
                parent[root(i)]=root(seen[key])
            else:
                seen[key]=i
    groups={}
    for i,row in enumerate(rows):
        groups.setdefault(root(i),[]).append(row)
    train,test=[],[]
    for group in groups.values():
        digest=hashlib.sha256('|'.join(sorted(row['id'] for row in group)).encode()).hexdigest()
        (test if int(digest[:8],16)%5==0 else train).extend(group)
    assert not {r['customer'] for r in train}&{r['customer'] for r in test}
    assert not {normalize(redact(r['text'])) for r in train}&{normalize(redact(r['text'])) for r in test}
    assert not {tuple(sorted(tokens(r['text']))) for r in train}&{tuple(sorted(tokens(r['text']))) for r in test}
    return train,test,len(groups)


def metrics(rows, classifier):
    result={}
    for signal in SIGNALS:
        counts=dict(tp=0,fp=0,fn=0,tn=0,unsupported=0)
        for row in rows:
            predicted=classifier(row['text'])[signal]
            actual=row['labels'][signal]
            if predicted is None:
                counts['unsupported']+=1
                continue
            counts['tp' if actual and predicted else 'fn' if actual else 'fp' if predicted else 'tn']+=1
        tp,fp,fn=counts['tp'],counts['fp'],counts['fn']
        counts.update(precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None,
            f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)
        result[signal]=counts
    return result


def train():
    started=time.monotonic()
    rows,missing=labeled_rows()
    training,holdout,groups=grouped_split(rows)
    if not training or not holdout:
        raise ValueError('No valid training/evaluation partition')
    model=fit(training)
    model['training_ids']=[r['id'] for r in training]
    model['evaluation_ids']=[r['id'] for r in holdout]
    MODEL.parent.mkdir(parents=True,exist_ok=True)
    MODEL.write_text(json.dumps(model,sort_keys=True),encoding='utf-8')
    report={'model_version':model['version'],'available':len(rows),'excluded_rows':len(missing),
        'protected_content_excluded':sum(':protected_content_excluded' in reason for reason in missing),
        'missing_source_rows':sum(':protected_content_excluded' not in reason for reason in missing),
        'training_rows':len(training),'evaluation_rows':len(holdout),'connected_groups':groups,
        'split':'SHA256 of sorted component source IDs modulo 5; shared customer, normalized redacted text or complete token signature joins components',
        'model_sha256':hashlib.sha256(MODEL.read_bytes()).hexdigest(),'duration_seconds':round(time.monotonic()-started,3),
        'trained':metrics(holdout,lambda text:{k:v['flag'] for k,v in predict(text,model).items()}),
        'live_review_signals':metrics(holdout,lambda text:review_signals(text,predict(text,model))),
        'rules_baseline_version':VERSION,'rules_baseline':metrics(holdout,extract),
        'by_source':{kind:metrics([r for r in holdout if r['kind']==kind],lambda text:{k:v['flag'] for k,v in predict(text,model).items()}) for kind in ('note','transcript')},
        'limitations':['Public development labels, not an organizer hidden test. Existing rules were previously evaluated on public labels.',
            'Possible hardship is counted positive. Rare-class results require inspection of support counts.',
            'Static text classification only; no historical customer-outcome or treatment-effect model.',
            'Model has not been tuned using evaluation examples. Scores are uncalibrated.']}
    (ROOT/'reports/classifier_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['train'])
    parser.parse_args()
    train()
