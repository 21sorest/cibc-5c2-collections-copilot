"""Employee conversation assistance. Customer text is evidence, never an instruction."""
import json

from pipeline import DEFAULT_RELEASE
from questions import policy_answer
from text_signals import extract
from train_classifier import MODEL, predict, review_signals

# Customer-facing templates offer no translated programme terms or eligibility promises.
FRENCH_REPLIES={
    'identity':'Avant de discuter des renseignements de votre compte, veuillez suivre la procédure approuvée de vérification de votre identité.',
    'closed':'Le statut actuel du dossier doit être vérifié avant toute discussion concernant un paiement. Je vais demander à la personne responsable de le vérifier.',
    'hold':'Je comprends votre préoccupation. Je vais transmettre votre demande à la personne spécialisée pour examiner les restrictions de communication et les prochaines étapes.',
    'dispute':'Je comprends que vous contestez le montant ou la transaction. Précisons ce qui est contesté afin que le service approprié puisse examiner votre demande.',
    'hardship':'Merci de nous avoir expliqué votre situation. Nous pouvons examiner les options de soutien et discuter de ce qui est abordable avant de demander un paiement.',
    'recorded_hardship':'Le dossier indique une difficulté financière antérieure. Vérifions si un soutien est toujours nécessaire et ce qui est abordable avant de demander un paiement.',
    'callback':'À quel moment et par quel moyen préférez-vous un suivi? La personne responsable vérifiera les restrictions de communication avant tout suivi.',
    'baseline':'Pouvez-vous expliquer ce qui empêche le paiement et si une entente existante devrait être examinée?',
    'policy_missing':'La politique applicable ne peut pas être vérifiée. La personne responsable doit examiner votre demande avant de faire une recommandation.'}


def assist(con, bundle, text, identity_verified=False, release=DEFAULT_RELEASE, use_model=True):
    if not isinstance(text,str) or not text.strip() or len(text)>12000:
        raise ValueError('Enter customer statements of 1 to 12,000 characters.')
    rules=extract(text)
    trained={}
    if use_model and MODEL.exists():
        trained=predict(text,json.loads(MODEL.read_text(encoding='utf-8')))
    signals=review_signals(text,trained,rules)
    f,c=bundle['features'],bundle['case']
    holds=f['action_eligibility'].startswith('hold_') or f['action_eligibility']=='representative_review'
    existing_dispute=f['action_eligibility']=='dispute_review'
    recorded_hardship=f.get('hardship_mention') is True or c.get('hardship_flag') is True
    case_open=c.get('case_status')=='open'
    language=bundle.get('controls',{}).get('preferred_language')
    payment_pause=not case_open or not identity_verified or language not in ('EN','FR') or holds or existing_dispute or signals['cease'] or signals['insolvency'] or signals['dispute']
    prompts=[]
    docs=['POL-COLL-001']
    if not identity_verified:
        reply_kind='identity'
        reply='Before discussing any account details, please complete the approved identity verification process.'
        prompts.append('Verify identity through the approved process before disclosing balances, account details or case information.')
    elif not case_open:
        reply_kind='closed'
        reply='The current case status must be verified before discussing payment. I will ask the assigned employee to review it.'
    elif holds or signals['cease'] or signals['insolvency']:
        reply_kind='hold'
        reply='I understand your concern. I will refer this to the appropriate specialist to review the communication restrictions and next steps.'
        prompts.append('Stop payment requests and route to the authorized specialist. A stated cease request needs review of its form and scope; do not treat a classifier as proof of legal status.')
    elif signals['dispute'] or existing_dispute:
        reply_kind='dispute'
        reply='I understand you are questioning the amount or transaction. Let us clarify what is disputed so the appropriate team can review it.'
    elif signals['hardship'] or recorded_hardship:
        payment_pause=True
        reply_kind='hardship'
        reply='Thank you for explaining your situation. We can review support options and discuss what is affordable before requesting a payment.'
        if recorded_hardship and not signals['hardship']:
            reply_kind='recorded_hardship'
            reply='The case has a recorded hardship signal. Let us confirm whether support is still needed and review what is affordable before requesting a payment.'
    elif signals['callback']:
        reply_kind='callback'
        reply='What time and channel would you prefer for a follow-up? I will have the employee check that the request meets the contact restrictions.'
    else:
        reply_kind='baseline'
        reply='Could you explain what is preventing payment and whether there is an existing arrangement we should review?'
    if signals['dispute'] or existing_dispute:
        docs.append('PRC-COLL-012')
        prompts.append('Clarify the disputed amount and transaction. Pause payment requests for the disputed amount and follow the dispute procedure; suspected fraud needs the fraud team.')
    if signals['hardship'] or recorded_hardship:
        docs.append('POL-COLL-004')
        prompts.append('Ask about the duration of the financial difficulty and affordable support. Verify program eligibility against the current policy; do not promise approval or request an unaffordable payment.')
        if recorded_hardship:
            prompts.append('A prior recorded signal is separate from the current statement. Confirm whether it still applies; do not infer that the customer repeated it today.')
    if signals['callback']:
        prompts.append('Confirm the requested date, time and channel. Recheck consent, contact limits, local hours and holds before any outbound follow-up.')
    policies=[policy_answer(con,doc,None,release) for doc in dict.fromkeys(docs)]
    if language=='FR':
        # EN policy remains available because supplied FR versions omit some sections.
        policies.extend(policy_answer(con,doc+'-FR',None,release,language='FR') for doc in dict.fromkeys(docs) if doc in ('POL-COLL-001','POL-COLL-004'))
    if any(doc['refused'] for doc in policies):
        reply_kind='policy_missing'
        reply='The applicable policy could not be verified. Refer this conversation to the assigned specialist before making a recommendation.'
        payment_pause=True
        prompts.insert(0,'Applicable policy is unavailable; do not infer program terms or permission.')
    if not case_open:
        prompts.insert(0,'Case status is not open or is unavailable. Pause payment requests and verify the current status with the assigned employee.')
    if language=='FR':
        reply=FRENCH_REPLIES[reply_kind]
        prompts.insert(0,'Preferred language is French. Use the French reply; verify any programme terms against the cited policy before discussing them.')
    elif language!='EN':
        reply='Do not send a customer-facing reply until the preferred language has been verified by the assigned employee.'
        prompts.insert(0,'Preferred language is unknown or unsupported. Pause payment requests and arrange assistance in the verified customer language.')
    if not payment_pause:
        prompts.append('Any proposed payment amount or date must be explicitly confirmed by the customer and reviewed by the employee; this draft creates no promise to pay.')
    note='Draft employee note. Customer-reported review signals, not independently verified: '+(', '.join(k for k,v in signals.items() if v) or 'none detected')+'.\nVerify and document only the relevant financial facts. Do not record protected characteristics.\nNo payment commitment or action was recorded by this assistant.'
    return {'case_id':c['case_id'],'summary':note,'proposed_step':reply,
        'suggested_reply':reply,'reply_language':language if language in ('EN','FR') else None,
        'reply_kind':reply_kind if language in ('EN','FR') else 'employee_language_review',
        'employee_prompts':prompts,'rules_signals':rules,'model_signals':trained,
        'signals':signals,'recorded_hardship_review':recorded_hardship,'identity_verified_by_employee':bool(identity_verified),'payment_request_paused':payment_pause,
        'payment_pause_scope':'Pause while a hold, identity/language check, dispute or hardship affordability/option review remains unresolved. This assistant never records that review as completed.',
        'model_use':'Hardship model contributes only at score >= 0.95 without an explicit denial; this heuristic score is uncalibrated. Rules may still detect a separate positive hardship statement.',
        'policies':policies,'sources':['employee-entered customer statement']+(['features:'+c['case_id'],'case:'+c['case_id']] if recorded_hardship else [])+[p['sql_or_sources'] for p in policies],
        'feature_version':f['definition_version'],'as_of_date':str(f['as_of_date']),
        'generator':'conversation-v0.3+local-nb' if trained else 'conversation-v0.3+rules',
        'requires_human_review':True,'scope':'In-conversation assistance only. No outbound contact permission, account changes or commitments are created.'}
