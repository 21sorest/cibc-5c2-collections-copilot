"""Evaluate potential-issue triage against public QA labels; no automatic QA score."""
import csv
import hashlib
import json
import duckdb
from collections import Counter
from calls import qa_evidence, structured_call_summary, CALL_VERSION
from features import safe_file
from pipeline import ROOT, DEFAULT_RELEASE


def evaluate():
    codes=['identity_verified_before_disclosure','recording_notice_given','agent_identified_self_and_purpose',
        'no_threatening_language','no_misleading_statements','fees_and_balance_stated_accurately',
        'hardship_handled_per_policy','options_offered_before_escalation','ptp_details_confirmed_back','respectful_close_and_next_steps']
    columns={code:f'qa{i:02d}_{code}' for i,code in enumerate(codes,1)}
    counts={key:dict(tp=0,fp=0,fn=0,pass_label_without_candidate=0,excluded=0,
        detector_statuses=Counter(),label_statuses=Counter(),evidence_rows=0) for key in columns}
    summary_counts=Counter()
    with (DEFAULT_RELEASE/'labels/call_transcripts_labels_public_500.csv').open(encoding='utf-8') as handle:
        labels=list(csv.DictReader(handle))
    with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
        paths=dict(con.execute("""SELECT t.transcript_id,t.file_path FROM curated.transcripts t
        WHERE t.transcript_id IN (SELECT unnest(?))""",[[r['transcript_id'] for r in labels]]).fetchall())
    found=0
    for row in labels:
        if row['transcript_id'] not in paths:
            continue
        body=json.loads(safe_file(DEFAULT_RELEASE,paths[row['transcript_id']]).read_text(encoding='utf-8'))
        evidence={r['item_code']:r for r in qa_evidence(body['turns'])}
        found+=1
        structured=structured_call_summary(body['turns'])
        summary_counts['calls_with_customer_situation']+=bool(structured['customer_situation'])
        summary_counts['calls_with_explicit_customer_commitments']+=bool(structured['commitments'])
        proposals=[item for item in structured['follow_ups'] if item['kind']=='payment proposal needs confirmation']
        summary_counts['explicit_customer_commitment_statements']+=len(structured['commitments'])
        summary_counts['customer_payment_proposal_candidates']+=len(proposals)
        summary_counts['calls_with_customer_payment_proposal_candidates']+=bool(proposals)
        summary_counts['proposals_with_unambiguous_amount_and_literal_date']+=sum(item.get('amount_text') is not None and item.get('date_text') is not None for item in proposals)
        summary_counts['calls_with_issue_mentions']+=bool(structured['unresolved_issues'])
        summary_counts['calls_with_follow_up_evidence']+=bool(structured['follow_ups'])
        ptp=evidence['ptp_details_confirmed_back']['observations']
        for key in ('proposal_matching_readbacks','proposal_mismatching_readbacks','ambiguous_readbacks','unresolved_date_readbacks'):
            summary_counts[key]+=ptp[key]
        for key,column in columns.items():
            counts[key]['detector_statuses'][evidence[key]['status']]+=1
            counts[key]['label_statuses'][row[column]]+=1
            counts[key]['evidence_rows']+=bool(evidence[key]['evidence'])
            if row[column] not in ('pass','fail'):
                counts[key]['excluded']+=1
                continue
            actual=row[column]=='fail'
            predicted=evidence[key]['status']=='potential_issue'
            counts[key]['tp' if actual and predicted else 'fn' if actual else 'fp' if predicted else 'pass_label_without_candidate']+=1
    for value in counts.values():
        tp,fp,fn=value['tp'],value['fp'],value['fn']
        value['precision']=tp/(tp+fp) if tp+fp else None
        value['recall']=tp/(tp+fn) if tp+fn else None
        value['actual_label_failures']=tp+fn
        value['metric_meaning']='Precision/recall of potential-issue flags against public fail labels; no-candidate and evidence_found are not compliance pass verdicts.'
    report={'version':CALL_VERSION,'code_sha256':hashlib.sha256((ROOT/'calls.py').read_bytes()).hexdigest(),
        'label_source':'call_transcripts_labels_public_500.csv','label_rows':len(labels),'evaluated':found,'excluded_unapproved_transcripts':len(labels)-found,'potential_issue_triage':counts,'structured_summary_evidence_coverage':dict(summary_counts),
        'limitations':['Public development labels previously inspected and used during development tuning; no independent or hidden-test claim.',
            'All ten checklist statuses/evidence coverage are evaluated; candidate-issue precision/recall applies only where a detector emits potential_issue.',
            'Evidence_found means observable evidence, not a pass. needs_review and applicability_needs_review remain unknown, not true negatives or passes.',
            'Independent synthetic regression fixtures check summary privacy, own commitments, proposal terms and read-back correctness; dataset coverage counts do not measure correctness.',
            'Summary section coverage is descriptive extraction coverage, not summary correctness or commitment accuracy. Proposal read-back mismatches do not establish that a promise was taken.',
            'Call-time financial accuracy and programme eligibility cannot be evaluated from current source facts.',
            'An undetected issue is not a pass. No automatic score or compliance certification is generated.']}
    (ROOT/'reports/qa_evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    evaluate()
