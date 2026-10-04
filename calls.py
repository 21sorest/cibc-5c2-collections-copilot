"""Post-call signal summary and QA evidence triage, not an automatic compliance verdict."""
import json
import calendar
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from assistant import records
from features import safe_file
from pipeline import DEFAULT_RELEASE
from text_signals import VERSION, extract, normalize, redact, negated_match


CALL_VERSION='post-call-extractive-v0.5'
AMOUNT_PATTERN=r'(?:\$\s*\d[\d,]*(?:\.\d{1,2})?|\b(?:CAD|C\$)\s*\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s*(?:dollars?|CAD)\b)'
DATE_PATTERN=r'\b(?:20\d\d-\d\d-\d\d|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\s+\d{1,2}(?:,?\s+20\d\d)?|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)|tomorrow|today|demain|aujourd.hui|(?:next\s+)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\s+prochain)?)\b'
IDENTITY_PATTERN=r'date (?:of birth|de naissance)|birth date|\bdob\b|verify.{0,25}identity|confirm.{0,25}identity|verifi.{0,25}identite|confirm.{0,40}(?:email|phone|address)|confirme.{0,40}(?:courriel|telephone|adresse)'
PROTECTED_CONTEXT=r'\b(?:gender|citizenship|religion|religious|marital|married|divorced|immigrant|newcomer|canadian|permanent resident|nationality|ethnicity|race|handicape|citoyennete|religieux|marie|divorce)\b|\bi am (?:a woman|a man|\d+ years old)\b'
OPTION_PATTERN=r'option|arrangement|reduced payment|deferral|payment plan|hardship program|skip.{0,15}payment|paiement reduit|report de paiement|entente|programme'
PAYMENT_REQUEST=r'(?:full|whole|entire) amount is (?:still )?due|montant total.{0,15}(?:du|exigible)|can you (?:pay|make.{0,15}payment)|(?:could|would) you.{0,20}(?:pay|make.{0,15}payment)|will you be paying|how would you like to make.{0,15}payment|(?:need|must|have to).{0,20}(?:pay|payment)|pay.{0,20}(?:today|now)|payment.{0,15}(?:today|now)|pouvez.vous payer|(?:devez|faut).{0,15}payer|payer.{0,20}(?:aujourd|maintenant)|comment.{0,25}(?:faire|effectuer).{0,15}paiement'
ESCALATION_PATTERN=r'transfer|escalat|refer.{0,25}(?:specialist|team)|transfert|transferer|transmettre.{0,25}(?:equipe|specialiste)'


def validate_call_turns(turns):
    if not isinstance(turns,list):
        raise ValueError('Malformed call evidence; review the original recording.')
    seen=set()
    for turn in turns:
        if not isinstance(turn,dict) or turn.get('speaker') not in ('agent','customer','third_party') or not isinstance(turn.get('text'),str) or not isinstance(turn.get('start_sec'),(int,float)) or isinstance(turn.get('start_sec'),bool) or not math.isfinite(turn['start_sec']) or turn['start_sec']<0:
            raise ValueError('Malformed call evidence; review the original recording.')
        key=(turn['speaker'],turn['start_sec'],turn['text'])
        if key in seen:
            raise ValueError('Malformed call evidence; duplicate source turn requires review.')
        seen.add(key)


def payment_denied(text,match):
    # Negation belongs to its clause; a later affirmative demand after "but" is independent.
    preceding=re.split(r'[.!?;]|\bbut\b|\bmais\b',text[:match.start()])[-1]
    clause=preceding+text[match.start():match.end()]
    return bool(re.search(r"\b(?:do not|don.t|never|no need|not required|not necessary|cannot|can.t)\b|\bne\b.{0,35}\bpas\b",clause))


def literal_date_key(value):
    """Normalize spelled month aliases only; never supply a missing year or relative anchor."""
    text=normalize(value)
    months={name.lower():index for index,name in enumerate(calendar.month_name) if name}
    months.update({name.lower():index for index,name in enumerate(calendar.month_abbr) if name})
    months['sept']=9
    months.update({name:index for index,name in enumerate(('janvier','fevrier','mars','avril','mai','juin','juillet','aout','septembre','octobre','novembre','decembre'),1)})
    for name,month in months.items():
        match=re.fullmatch(re.escape(name)+r'\s+(\d{1,2})(?:,?\s+(20\d\d))?',text)
        reverse=re.fullmatch(r'(\d{1,2})\s+'+re.escape(name),text)
        if match or reverse:
            return (month,int((match or reverse)[1]),match[2] if match else None)
    return text


def financial_customer_turns(turns):
    """Reuse the catalogue's verification-response filtering before any new customer display."""
    from questions import financial_call_evidence
    safe=[]
    for line in financial_call_evidence(turns):
        match=re.match(r'^\[([\d.]+)s\] Customer: (.*)$',line)
        if match:
            safe.append({'start_sec':float(match[1]),'speaker':'customer','text':match[2]})
    return safe


def structured_call_summary(turns):
    validate_call_turns(turns)
    customers=financial_customer_turns(turns)
    situation=[]
    commitments=[]
    issues=[]
    follow=[]
    for turn in customers:
        text=turn['text']
        normalized=normalize(text)
        flags=extract(text)
        quote={'start_sec':turn['start_sec'],'speaker':'customer','quote':
            '[Personal context omitted; verify relevant financial facts in the recording.]' if re.search(PROTECTED_CONTEXT,normalized) else text}
        if len(text.strip())>8:
            situation.append({**quote,'review_signals':[key for key,value in flags.items() if value]})
        for issue in ('hardship','dispute','cease','insolvency'):
            if flags[issue]:
                issues.append({**quote,'issue':issue,'resolution_state':'not established by the extractor'})
        original=[item['text'] for item in turns if item['speaker']=='customer' and float(item['start_sec'])==turn['start_sec']]
        commitment_text=original[0] if len(original)==1 else text
        amounts=list(re.finditer(AMOUNT_PATTERN,commitment_text,re.I))
        dates=list(re.finditer(DATE_PATTERN,normalize(commitment_text),re.I))
        amount=amounts[0] if amounts else None
        day=dates[0] if dates else None
        intent=re.match(r"^(?:(?:okay|ok|yes|sure|all right|oui|d.accord)[, .:;!]+)?(?:(?:i|we)\s+(?:will|shall|am going to|are going to)\s+(?:pay|make.{0,15}payment)|i.ll\s+pay|je\s+(?:vais|m.engage a)\s+(?:payer|faire.{0,15}paiement))",normalized.strip())
        proposal_intent=re.search(r"\b(?:i|we).{0,15}(?:can|could|will|would|might|want to|plan to).{0,20}(?:pay|payment)|\bi.ll\s+pay|\bje.{0,15}(?:peux|vais|pourrais).{0,15}(?:payer|paiement)",normalized)
        conditional=bool(re.search(r'\b(?:if|might|could|would|si|pourrais)\b|\bmay\s+pay\b|peut.etre',normalized))
        denied=bool(re.search(r"\b(?:cannot|can.t|won.t|will not|never|not promise|not guarantee|not commit|no promise|no commitment)\b|\bne.{0,35}pas\b",normalized))
        reported=bool(re.search(r'\b(?:said|says|told|quoted|quote|reported|according to|my spouse|my husband|my wife|my partner|selon|disait)\b|\ba dit\b',normalized))
        withdrawn=not reported and bool(re.search(r"\b(?:i|we)\s+(?:cannot|can.t|won.t|will not|can no longer|am unable to)\s+(?:pay|make.{0,15}payment)|\b(?:cancel|withdraw|retract).{0,25}(?:payment|promise|commitment)|\bje ne.{0,20}(?:peux|vais).{0,20}pas.{0,20}payer",normalized))
        if withdrawn:
            commitments=[]
            follow=[item for item in follow if item['kind']!='payment proposal needs confirmation']
            follow.append({**quote,'kind':'customer withdrew payment terms','confirmed_commitment':False,'requires_employee_confirmation':True})

        if intent and len(amounts)==1 and len(dates)==1 and not conditional and not denied and not reported:
            commitments.append({**quote,'amount_text':amount[0],'date_text':day[0],
                'specificity':'explicit customer payment statement; literal date only','requires_employee_confirmation':True})
        elif proposal_intent and not denied and not reported and (amount or day):
            follow.append({**quote,'kind':'payment proposal needs confirmation','amount_text':amount[0] if len(amounts)==1 else None,
                'date_text':day[0] if len(dates)==1 else None,'terms_ambiguous':len(amounts)>1 or len(dates)>1,
                'confirmed_commitment':False,'requires_employee_confirmation':True})
        elif not denied and not reported and re.search(r'(?:i|we).{0,15}(?:can do|can manage|can afford)|je.{0,15}(?:peux faire|peux verser)',normalized) and (amount or day):
            follow.append({**quote,'kind':'payment proposal needs confirmation','amount_text':amount[0] if len(amounts)==1 else None,
                'date_text':day[0] if len(dates)==1 else None,'terms_ambiguous':len(amounts)>1 or len(dates)>1,
                'confirmed_commitment':False,'requires_employee_confirmation':True})
        if flags['callback']:
            follow.append({**quote,'kind':'customer callback request','confirmed_commitment':False})
    cutoff=min((turn['start_sec'] for turn in customers),default=None)
    if cutoff is not None:
        for turn in turns:
            text=normalize(turn['text'])
            if turn['speaker']=='agent' and float(turn['start_sec'])>=cutoff and not re.search(IDENTITY_PATTERN,text) and re.search(r'(?:i|we|je|nous).{0,25}(?:send|call|refer|review|envoyer|rappel|transmettre)|next step|prochaine etape|confirmation|payment link|lien de paiement',text):
                follow.append({'start_sec':turn['start_sec'],'speaker':'agent','quote':
                    '[Personal context omitted; verify follow-up in the recording.]' if re.search(PROTECTED_CONTEXT,text) else redact(turn['text']),
                    'kind':'agent proposed follow-up, not an executed action','confirmed_commitment':False})
    chronology_monotonic=all(float(left['start_sec'])<=float(right['start_sec']) for left,right in zip(turns,turns[1:]))
    if not chronology_monotonic:
        commitments=[]
        follow=[item for item in follow if item['kind']!='payment proposal needs confirmation']
    return {'customer_situation':situation[:12],'commitments':commitments,'unresolved_issues':issues,
        'follow_ups':follow,'extraction_limits':['Customer evidence follows financial_call_evidence identity-response filtering and its 24-entry bound.',
            'Payment terms are withheld when source timestamps run backwards; source chronology requires employee review.',
            'Numeric currency amounts and explicit literal dates only. Relative dates are not converted to calendar dates.',
            'Multiple amounts or dates in a customer statement remain an unconfirmed proposal, avoiding incorrect value binding.',
            'Agent offers, conditional proposals and generic acknowledgments do not create customer payment commitments. Later explicit withdrawal removes earlier payment terms from active extraction.',
            'Personal-context omission is a keyword safeguard, not comprehensive PII detection; employees must review excerpts.',
            'Issue mentions do not establish that an issue is unresolved or resolved; employee review is required.']}


def qa_evidence(turns):
    validate_call_turns(turns)
    source_order={id(turn):index for index,turn in enumerate(turns)}
    timestamps=[float(turn['start_sec']) for turn in turns]
    chronology_monotonic=all(left<=right for left,right in zip(timestamps,timestamps[1:]))
    agents=[turn for turn in turns if turn['speaker']=='agent']
    customers=financial_customer_turns(turns)
    def find(pattern,ignore_negated=False):
        evidence=[]
        for turn in agents:
            text=normalize(turn['text'])
            for match in re.finditer(pattern,text):
                prefix=text[:match.start()]
                denied=negated_match(text,match) or bool(re.search(r"\b(?:cannot|can.t|won.t|will not|not allowed to|not going to|never|not)\s+(?:(?:be|a|an)\s+)?$|\bne.{0,30}pas(?:\s+vous)?\s*$",prefix))
                if pattern==PAYMENT_REQUEST:
                    denied=denied or payment_denied(text,match)
                if not ignore_negated or not denied:
                    evidence.append(turn)
                    break
        return evidence
    def first(items):
        return min((float(turn['start_sec']) for turn in items),default=None)
    def position(items,pattern):
        positions=[(float(turn['start_sec']),source_order[id(turn)],match.start()) for turn in items for match in re.finditer(pattern,normalize(turn['text'])) if pattern!=PAYMENT_REQUEST or not payment_denied(normalize(turn['text']),match)]
        return min(positions,default=None)
    def evidence(items):
        unique={(float(turn['start_sec']),turn['speaker'],turn['text']):turn for turn in items}
        ordered=sorted(unique.values(),key=lambda turn:(float(turn['start_sec']),source_order.get(id(turn),-1)))
        return [{'start_sec':turn['start_sec'],'speaker':turn['speaker'],
            'text':'Identity verification prompt; personal response omitted.' if re.search(IDENTITY_PATTERN,normalize(turn['text'])) else
                '[Personal context omitted; review financial evidence in the recording.]' if re.search(PROTECTED_CONTEXT,normalize(turn['text'])) else redact(turn['text'])}
            for turn in ordered[:6]]
    rows=[]
    def add(code,status,reason,items=(),applicability='requires employee review',observations=None,source_check=False):
        rows.append({'item_code':code,'status':status,'reason':reason,'evidence':evidence(items),
            'applicability':applicability,'observations':observations or {},'needs_source_verification':source_check})
    verification=find(IDENTITY_PATTERN)
    disclosure=find(r'past due|amount.{0,20}\$|balance.{0,20}\$|montant.{0,25}(?:du|\$)|solde.{0,20}(?:du|\$)|en souffrance')
    responses=[turn for turn in turns if turn['speaker']=='customer' and verification and float(turn['start_sec'])>first(verification)]
    identity_status='needs_review'
    verification_position=position(verification,IDENTITY_PATTERN)
    disclosure_position=position(disclosure,r'past due|amount.{0,20}\$|balance.{0,20}\$|montant.{0,25}(?:du|\$)|solde.{0,20}(?:du|\$)|en souffrance')
    if verification_position and disclosure_position and disclosure_position<verification_position:
        identity_status='potential_issue'
    elif verification and disclosure and responses and first(verification)<first(responses)<first(disclosure):
        identity_status='evidence_found'
    add('identity_verified_before_disclosure',identity_status,
        'Detected chronology only. An identity prompt and response do not establish successful identity verification; verify the approved process.' if identity_status!='potential_issue' else 'Account disclosure precedes the first detected identity prompt.',
        verification+disclosure,observations={'prompt_sec':first(verification),'response_sec':first(responses),'disclosure_sec':first(disclosure),
            'same_turn_order_unknown':False,'prompt_position':verification_position,'disclosure_position':disclosure_position},source_check=True)
    notice=[turn for turn in find(r'call.{0,25}recorded|appel.{0,25}enregistre') if not re.search(r'not.{0,15}recorded|pas.{0,15}enregistre',normalize(turn['text']))]
    late=bool(notice and (first(disclosure) is not None and first(notice)>first(disclosure) or agents and first(notice)>float(agents[min(1,len(agents)-1)]['start_sec'])))
    add('recording_notice_given','potential_issue' if late else 'evidence_found' if notice else 'needs_review',
        'Notice occurred after the opening or account disclosure.' if late else 'Check notice wording and the call opening; missing ASR evidence is unknown.',notice)
    bank=find(r'maple bank|banque maple')
    name=find(r'this is|my name is|je m.appelle|ici.{0,25}(?:banque|maple)')
    purpose=find(r'calling about|call concerns|account.{0,30}past due|appel.{0,35}(?:compte|solde)|compte.{0,30}souffrance')
    add('agent_identified_self_and_purpose','evidence_found' if bank and name and purpose else 'needs_review',
        'Review bank identification, caller self-identification and financial purpose separately.',bank+name+purpose,
        observations={'bank_identification':bool(bank),'self_identification':bool(name),'purpose':bool(purpose)})
    threats=find(r'garnish|arrest|criminal matter|sue you|legal action tomorrow|saisir.{0,20}salaire|saisie.{0,20}salaire|arreter|poursuite.{0,20}demain',True)
    misleading=find(r'criminal matter|arrest|criminal offence|criminel|arreter|prison',True)
    for code,items in [('no_threatening_language',threats),('no_misleading_statements',misleading)]:
        add(code,'potential_issue' if items else 'needs_review','Review assertion, negation and quotation context. No detected candidate is unknown, not a compliance pass.',items)
    amounts=[turn for turn in disclosure if re.search(AMOUNT_PATTERN,turn['text'],re.I)]
    add('fees_and_balance_stated_accurately','needs_review','Extracted amounts require matching call-time account and fee evidence; the current snapshot cannot establish historical accuracy.',amounts,source_check=True)
    hardship=[turn for turn in customers if extract(turn['text'])['hardship']]
    acknowledgment=find(r'sorry to hear|understand.{0,30}(?:situation|difficult)|thank.{0,25}explaining|desole|comprends.{0,30}(?:situation|difficulte)|merci.{0,25}expliqu')
    options=find(OPTION_PATTERN)
    requests=find(PAYMENT_REQUEST,True)
    after=lambda items,stamp:[turn for turn in items if stamp is not None and float(turn['start_sec'])>=stamp]
    ack_after=after(acknowledgment,first(hardship))
    option_after=after(options,first(hardship))
    pay_after=after(requests,first(hardship))
    ack_position=position(ack_after,r'sorry to hear|understand.{0,30}(?:situation|difficult)|thank.{0,25}explaining|desole|comprends.{0,30}(?:situation|difficulte)|merci.{0,25}expliqu')
    option_position=position(option_after,OPTION_PATTERN)
    request_position=position(pay_after,PAYMENT_REQUEST)
    hardship_issue=bool(hardship and request_position and (not ack_position or not option_position or request_position<max(ack_position,option_position)))
    same_turn_order=False
    add('hardship_handled_per_policy','applicability_needs_review' if not hardship else 'potential_issue' if hardship_issue else 'needs_review' if same_turn_order else 'evidence_found' if ack_after and option_after else 'needs_review',
        'Customer difficulty, acknowledgment, options and payment-request ordering are separate observations. Programme eligibility requires applicable call-time evidence.',
        hardship+ack_after+option_after+pay_after,applicability='customer hardship mention detected' if hardship else 'hardship applicability not established',
        observations={'hardship_sec':first(hardship),'acknowledgment_sec':first(ack_after),'option_sec':first(option_after),
            'payment_request_sec':first(pay_after),'same_turn_order_unknown':same_turn_order,
            'acknowledgment_position':ack_position,'option_position':option_position,'payment_request_position':request_position},source_check=True)
    escalation=find(ESCALATION_PATTERN)
    option_before=[turn for turn in options if escalation and float(turn['start_sec'])<first(escalation)]
    same_turn_before=[turn for turn in options if escalation and float(turn['start_sec'])==first(escalation) and re.search(r'before.{0,25}transfer|avant.{0,25}transfer',normalize(turn['text']))]
    same_turn_unknown=bool(escalation and any(float(turn['start_sec'])==first(escalation) for turn in options) and not same_turn_before)
    required_specialist=any(extract(turn['text'])[key] for turn in customers for key in ('cease','insolvency','dispute'))
    add('options_offered_before_escalation','applicability_needs_review' if not escalation or required_specialist else 'evidence_found' if option_before or same_turn_before else 'needs_review' if same_turn_unknown else 'potential_issue',
        'Check whether offering payment options before transfer is appropriate. Cease, insolvency and dispute transfers require specialist handling; do not encourage payment options to bypass a hold.',
        options+escalation,observations={'escalation_sec':first(escalation),'option_before_escalation':bool(option_before),
            'same_turn_before_transfer_wording':bool(same_turn_before),'same_turn_order_unknown':same_turn_unknown,'specialist_restriction_signal':required_specialist},source_check=True)
    structured=structured_call_summary(turns)
    commitments=structured['commitments']
    proposals=[item for item in structured['follow_ups'] if item['kind']=='payment proposal needs confirmation']
    terms=[{**item,'explicit':True} for item in commitments]+[{**item,'explicit':False} for item in proposals]
    confirmation=find(r'just to confirm|confirm.{0,25}payment|pour confirmer|confirme.{0,25}paiement')
    compared={'matching':[],'mismatching':[],'proposal_matching':[],'proposal_mismatching':[],'unresolved_date':[],'ambiguous':[]}
    for turn in confirmation:
        prior=[item for item in terms if float(item['start_sec'])<float(turn['start_sec'])]
        if not prior:
            continue
        latest=max(float(item['start_sec']) for item in prior)
        candidate=[item for item in prior if float(item['start_sec'])==latest]
        amounts=list(re.finditer(AMOUNT_PATTERN,turn['text'],re.I))
        dates=list(re.finditer(DATE_PATTERN,normalize(turn['text']),re.I))
        if len(candidate)!=1 or len(amounts)!=1 or len(dates)!=1 or not candidate[0].get('amount_text') or not candidate[0].get('date_text'):
            compared['ambiguous'].append(turn)
            continue
        term=candidate[0]
        # Nonstandard comma grouping may be a locale decimal; do not guess its value.
        numeric=lambda value:re.sub(r'[^\d.,]','',value)
        values=[numeric(amounts[0][0]),numeric(term['amount_text'])]
        if any(',' in value and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?',value) for value in values):
            compared['ambiguous'].append(turn)
            continue
        money=lambda value:Decimal(value.replace(',',''))
        amount_matches=money(values[0])==money(values[1])
        day=dates[0][0]
        date_matches=literal_date_key(day)==literal_date_key(term['date_text'])
        prefix='' if term['explicit'] else 'proposal_'
        if amount_matches and date_matches:
            compared[prefix+'matching'].append(turn)
        elif not amount_matches or (re.fullmatch(r'20\d\d-\d\d-\d\d',day) and re.fullmatch(r'20\d\d-\d\d-\d\d',term['date_text'])):
            compared[prefix+'mismatching'].append(turn)
        else:
            compared['unresolved_date'].append(turn)
    mismatch=compared['mismatching']
    status='potential_issue' if mismatch else 'evidence_found' if compared['matching'] else 'needs_review' if terms else 'applicability_needs_review'
    add('ptp_details_confirmed_back',status,
        'Compare the most recent customer terms with later read-back. Proposal mismatches remain review observations, not evidence a promise was taken; matching proposals remain unconfirmed. Generic assent does not create a promise, and relative dates remain literal.',confirmation,
        observations={'explicit_customer_commitments':len(commitments),'customer_proposal_candidates':len(proposals),
            'matching_readbacks':len(compared['matching']),'mismatching_readbacks':len(compared['mismatching']),
            'proposal_matching_readbacks':len(compared['proposal_matching']),'proposal_mismatching_readbacks':len(compared['proposal_mismatching']),
            'unresolved_date_readbacks':len(compared['unresolved_date']),'ambiguous_readbacks':len(compared['ambiguous'])},source_check=True)
    thanks=find(r'thank you|merci')
    next_steps=find(r'confirmation|next step|send.{0,25}(?:link|text|email)|prochaine etape|envoyer.{0,25}(?:lien|texto|courriel)')
    closing=bool(thanks and next_steps and agents and max(float(turn['start_sec']) for turn in thanks)>=float(agents[max(0,len(agents)-3)]['start_sec']))
    add('respectful_close_and_next_steps','evidence_found' if closing else 'needs_review','A courteous phrase alone does not establish a complete closing; review agreed next steps and the end of the call.',thanks+next_steps,
        observations={'courteous_close_detected':closing,'next_step_detected':bool(next_steps)})
    metadata=[(12,True,'Right-party contact'),(6,False,'All calls'),(6,False,'All calls'),(14,True,'All calls'),
        (12,True,'All calls'),(8,False,'Right-party contact'),(18,True,'Hardship stated by customer'),
        (8,False,'Escalation or transfer'),(8,False,'Promise taken'),(8,False,'Right-party contact')]
    for row,(weight,critical,applies_when) in zip(rows,metadata):
        row.update(weight=weight,critical_flag=critical,applies_when=applies_when,checklist_version='QA-2026.2',automatic_compliance_verdict=False)
    temporal={'identity_verified_before_disclosure','recording_notice_given','hardship_handled_per_policy',
        'options_offered_before_escalation','ptp_details_confirmed_back','respectful_close_and_next_steps'}
    for row in rows:
        if row['item_code'] in temporal:
            row['observations']['source_chronology_monotonic']=chronology_monotonic
            row['observations']['position_format']='timestamp, source-turn index, intra-turn text offset'
            if not chronology_monotonic:
                row['status']='needs_review'
                row['reason']='Source timestamps run backwards; review transcript chronology before assessing ordering. '+row['reason']
    return rows


def post_call(con,case_id,release=DEFAULT_RELEASE,when=None):
    if when is not None and (not isinstance(when,datetime) or when.tzinfo is None):
        raise ValueError('Review cutoff must be a timezone-aware datetime.')
    cutoff=min(when.astimezone(timezone.utc).replace(tzinfo=None),datetime(2026,9,28,23,59,59,999999)) if when is not None else datetime(2026,9,28,23,59,59,999999)
    rows=records(con,"""SELECT t.transcript_id,t.file_path,t.call_start_ts FROM curated.transcripts t
        WHERE t.case_id=? AND try_cast(t.call_start_ts AS TIMESTAMP)<=?
        ORDER BY try_cast(t.call_start_ts AS TIMESTAMP) DESC LIMIT 1""",[case_id,cutoff])
    if not rows:
        raise ValueError('No identity-matched recorded call is available for this case.')
    row=rows[0]
    body=json.loads(safe_file(release,row['file_path']).read_text(encoding='utf-8'))
    turns=body.get('turns') if isinstance(body,dict) else None
    validate_call_turns(turns)
    structured=structured_call_summary(turns)
    events=[]
    for turn in financial_customer_turns(body['turns']):
        if turn['speaker']=='customer':
            flags=extract(turn['text'])
            if any(flags.values()):
                events.append({'start_sec':turn['start_sec'],'signals':[k for k,v in flags.items() if v]})
    summary='Recorded customer signals: '+('; '.join(str(e['start_sec'])+'s: '+', '.join(e['signals']) for e in events) or 'none detected by the rules')+f". Explicit customer payment statements with amount/date: {len(structured['commitments'])}. Employee must confirm them; no promise is created."
    return {'case_id':case_id,'transcript_id':row['transcript_id'],'call_start_ts':str(row['call_start_ts']),
        'review_cutoff':when.isoformat() if when is not None else None,'summary':summary,
        'proposed_step':'Review signal timestamps and QA evidence against the recording and policy before finalizing the note or coaching.',
        'signal_events':events,'structured_summary':structured,'qa':qa_evidence(body['turns']),
        'sources':['transcript:'+row['transcript_id'],'raw.qa_checklist QA-2026.2'],
        'generator':CALL_VERSION,'feature_version':VERSION,'as_of_date':'2026-09-28',
        'requires_human_review':True,'limitations':['No automatic compliance verdict, disciplinary action or numeric QA score.',
            'Missing evidence is unknown, not proof of failure. Keyword evidence does not establish contextual correctness.',
            'Historical amount correctness and eligibility require call-time evidence unavailable in this current snapshot.',
            'Call timestamp filtering treats offset-free source call_start_ts as UTC; relative promise dates are never resolved from it.',
            'Personal-context omission is heuristic, not comprehensive PII detection; review excerpts before recording them.']}
