"""Local synthetic-data Collections Copilot demo."""
from datetime import datetime, timezone
import json
import time

import duckdb
import streamlit as st

from assistant import draft_brief, load_case, save_review, reviewed_checklist
from features import FEATURE_NAMES, safe_file
from pipeline import ROOT, DEFAULT_RELEASE
from questions import answer
from llm import enhance_summary, settings
from access import USERS,users,authenticate,authorize_case
from conversation import assist
from decisions import recommend
from calls import post_call
from local_llm import MODEL as LOCAL_MODEL, enhance_summary as enhance_local_summary
from speech import approved_cached_audio
from trained_llm import available as trained_available, enhance_summary as enhance_trained_summary

st.set_page_config(page_title='Collections Copilot',page_icon='📋',layout='wide')
st.title('Collections Copilot')
st.caption('Team 5C2 · Synthetic Maple Bank data · Snapshot 28 September 2026')
st.info('Local employee-review demo. Data reflects the supplied snapshot. No messages or payment changes are executed.')

if USERS.exists():
    actor=st.session_state.get('actor')
    registry=users()
    if actor and (time.time()>st.session_state.get('login_until',0) or registry.get(actor['name'],{}).get('password_hash')!=actor['credential_version']):
        st.session_state.clear()
        actor=None
    if not actor:
        with st.form('login'):
            username=st.text_input('Username')
            password=st.text_input('Password',type='password')
            submitted=st.form_submit_button('Sign in')
        if submitted:
            if time.time()<st.session_state.get('retry_after',0):
                st.error('Wait a minute before trying again.')
            else:
                actor=authenticate(username,password)
                if actor:
                    st.session_state['actor']=actor
                    st.session_state['login_until']=time.time()+3600
                    st.rerun()
                else:
                    failures=st.session_state.get('login_failures',0)+1
                    st.session_state['login_failures']=failures
                    if failures>=5:
                        st.session_state['retry_after']=time.time()+60
                    st.error('Invalid username or password.')
        st.stop()
    actor={**actor,'role':registry[actor['name']]['role'],'agent_id':registry[actor['name']]['agent_id']}
    st.sidebar.caption('Signed in as '+actor['name']+' ('+actor['role']+')')
    if st.sidebar.button('Sign out'):
        st.session_state.clear()
        st.rerun()
else:
    actor={'name':'local-demo-reviewer','role':'supervisor','agent_id':''}
    st.caption('Demo access: no account file is configured. Local password accounts and assignment checks activate after account setup.')

database=ROOT/'data/collections.duckdb'
if not database.exists():
    st.error('Build the data foundation first: python pipeline.py build')
    st.stop()

try:
    connection=duckdb.connect(str(database),read_only=True)
except duckdb.IOException:
    st.info('The dataset is being refreshed. Reopen this workspace after the build finishes.')
    st.stop()

with connection as con:
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='features' AND table_name='case_current'").fetchone()[0]:
        st.error('Build the feature snapshot first: python features.py build')
        st.stop()
    with st.sidebar:
        st.header('Case workspace')
        if actor['role']=='agent':
            assigned=[r[0] for r in con.execute("SELECT case_id FROM curated.cases WHERE assigned_agent_id=? AND case_status='open' ORDER BY case_id LIMIT 100",[actor['agent_id']]).fetchall()]
            if not assigned:
                st.warning('No open served cases are assigned to this agent.')
                st.stop()
            case_id=st.selectbox('Assigned case',assigned)
        else:
            case_id=st.text_input('Case ID',value='CS-2026-614370')
        reviewer=st.text_input('Reviewer name or employee ID',value=actor['name'],disabled=USERS.exists())
        channel=st.selectbox('Proposed channel',['call','sms','email'])
        simulation=st.checkbox('Use snapshot time for demonstration',value=True)
        st.caption('Snapshot simulation shows policy behaviour on the release date. Current-time checks block stale data.')
        when_text=st.text_input('Decision time, with UTC offset',value='2026-09-28T15:00:00+00:00',disabled=not simulation)
    try:
        when=datetime.fromisoformat(when_text) if simulation else datetime.now(timezone.utc)
        authorize_case(con,actor,case_id.strip())
        bundle=load_case(con,case_id.strip())
        brief=draft_brief(bundle,channel,when)
    except (ValueError,PermissionError,duckdb.Error) as error:
        st.error(str(error))
        st.stop()
    case=bundle['case']
    a,b,c,d=st.columns(4)
    a.metric('Days past due',bundle['features']['case_max_dpd'])
    b.metric('Case overdue CAD',str(bundle['features']['case_overdue_cad']))
    c.metric('Attempts in 7 snapshot dates',bundle['features']['contact_attempts_7d'])
    d.metric('Assigned queue',case['queue'])
    overview,signals,conversation,decisioning,postcall,review,questions=st.tabs(['Case evidence','12 features','Conversation assistance','Decision proposals','Post-call review','Review assistance','Ask a question'])
    with overview:
        st.subheader('Linked accounts')
        st.dataframe(bundle['accounts'],hide_index=True)
        st.subheader('Recent contacts')
        st.dataframe(bundle['contacts'],hide_index=True)
        st.subheader('Promises to pay')
        st.dataframe(bundle['promises'],hide_index=True)
        st.caption('Customer amounts cover matched accounts only. Empty tables and unknown values are not proof of no activity.')
    with signals:
        st.dataframe([{'feature':name,'value':str(bundle['features'][name])} for name in FEATURE_NAMES],hide_index=True)
        st.caption('Version '+bundle['features']['definition_version']+' · Rules-based text extractor · Current snapshot only')
        with st.expander('Text evidence references'):
            st.json(json.loads(bundle['features']['text_sources']))
    with conversation:
        st.subheader('Help during the customer conversation')
        st.caption('Enter customer statements only. This uses local classification, policy retrieval and reviewed response templates, with no paid calls.')
        with st.form('conversation_input:'+case_id.strip()):
            customer_text=st.text_area('What did the customer say?',max_chars=12000,key='customer_text:'+case_id.strip())
            verified=st.checkbox('Employee completed approved identity verification',value=False,key='identity_verified:'+case_id.strip())
            local_model=st.checkbox('Include locally trained hardship detection',value=True)
            generate=st.form_submit_button('Prepare conversation assistance')
        if generate:
            try:
                st.session_state['conversation_draft']=assist(con,bundle,customer_text,verified,use_model=local_model)
            except ValueError as error:
                st.error(str(error))
        conversation_draft=st.session_state.get('conversation_draft')
        if conversation_draft and conversation_draft['case_id']==case_id.strip():
            st.write(conversation_draft['suggested_reply'])
            if conversation_draft['payment_request_paused']:
                st.warning('Pause payment requests pending specialist review. This screen grants no contact permission.')
            for prompt in conversation_draft['employee_prompts']:
                st.write('• '+prompt)
            with st.expander('Detected signals and model evidence'):
                st.json({'rules':conversation_draft['rules_signals'],'trained':conversation_draft['model_signals']})
                st.caption('Model scores are uncalibrated. Rare-class model flags do not replace the rules or policy checks.')
            with st.expander('Current policy evidence'):
                for policy in conversation_draft['policies']:
                    st.caption(policy['sql_or_sources'])
                    st.text(policy['answer'])
            st.text_area('Draft conversation note for review',value=conversation_draft['summary'],disabled=True)
            with st.form('conversation_review:'+case_id.strip()):
                conversation_decision=st.radio('Conversation review decision',['accept','edit','reject'],horizontal=True)
                conversation_edit=st.text_area('Edited reply or note')
                conversation_reason=st.text_area('Conversation review reason')
                reviewed=st.form_submit_button('Record conversation review')
            if reviewed:
                try:
                    review_id=save_review(actor['name'] if USERS.exists() else reviewer.strip(),conversation_draft,conversation_decision,conversation_edit,conversation_reason)
                    st.success('Conversation review recorded: '+review_id+'. No action was executed.')
                except ValueError as error:
                    st.error(str(error))
    with decisioning:
        st.caption('Next Best Action, channel comparison and agent routing use current case evidence. These are proposals for employee review.')
        if st.button('Compare action, channels and routing'):
            try:
                st.session_state['decision_proposal']=recommend(con,bundle,when)
            except (ValueError,duckdb.Error) as error:
                st.error(str(error))
        proposal=st.session_state.get('decision_proposal')
        if proposal and proposal['case_id']==case_id.strip() and proposal['decision_time']==when.isoformat():
            st.write(proposal['next_best_action'])
            st.write(proposal['explanation'])
            if proposal.get('payment_request_paused'):
                st.warning('Payment requests are paused for this proposal. Review the restrictions and applicable policy.')
            if proposal.get('review_priority'):
                st.caption('Internal review priority: '+str(proposal['review_priority']))
            if proposal.get('decision_reasons'):
                st.subheader('Why this action')
                st.dataframe(proposal['decision_reasons'],hide_index=True)
            if proposal.get('alternatives'):
                with st.expander('Alternatives and prerequisites'):
                    st.dataframe(proposal['alternatives'],hide_index=True)
            for missing in proposal.get('missing_evidence',[]):
                st.caption('Needs verification: '+str(missing))
            if proposal.get('support_options'):
                st.subheader('Support programmes to review')
                st.caption('Published terms and initial screens only. Verify remaining requirements and approval before offering a programme.')
                for option in proposal['support_options']:
                    with st.expander(option['program_name']+' · '+option['review_state'].replace('_',' ')):
                        st.write(option['published_terms'])
                        for conflict in option.get('policy_conflicts',[]):
                            st.warning('Resolve policy conflict: '+conflict)
                        for exclusion in option.get('exclusion_reasons',[]):
                            st.warning(exclusion)
                        st.write('Before discussing approval:')
                        for check in option['remaining_checks']:
                            st.write('• '+check)
                        st.caption('Evidence: '+option['source'])
            st.subheader('Channel evidence and timing')
            st.write(proposal.get('channel_explanation',''))
            st.caption('Frequency checks conservatively count all recorded outbound non-system attempts because automated payment-reminder purpose is unavailable. Some contact may therefore be blocked beyond the policy call/reminder cap.')
            st.dataframe(proposal['channel_candidates'],hide_index=True)
            st.caption('Suggested channel: '+str(proposal['suggested_channel']))
            if proposal.get('comparison_order'):
                with st.expander('Tentative comparisons and unmet prerequisites'):
                    st.dataframe(proposal['comparison_order'],hide_index=True)
                st.caption('This order supports investigation. It grants no contact permission and does not establish the best treatment.')
            if proposal.get('timing_review'):
                with st.expander('Timing evidence and permitted window'):
                    st.json(proposal['timing_review'])
            st.subheader('Staff requirements and candidates')
            st.write(proposal.get('routing_explanation',''))
            if proposal.get('routing_requirements'):
                st.json(proposal['routing_requirements'])
            st.dataframe(proposal['routing_candidates'],hide_index=True)
            if proposal.get('roster_exclusions'):
                with st.expander('Why staff were excluded'):
                    st.json(proposal['roster_exclusions'])
            for limitation in proposal['limitations']:
                st.caption(limitation)
            with st.form('decision_review:'+case_id.strip()):
                proposal_decision=st.radio('Proposal review decision',['accept','edit','reject'],horizontal=True)
                proposal_edit=st.text_area('Edited decision proposal')
                proposal_reason=st.text_area('Decision proposal review reason')
                proposal_submit=st.form_submit_button('Record proposal review')
            if proposal_submit:
                try:
                    review_id=save_review(actor['name'] if USERS.exists() else reviewer.strip(),proposal,proposal_decision,proposal_edit,proposal_reason)
                    st.success('Proposal review recorded: '+review_id+'. No contact or reassignment was executed.')
                except ValueError as error:
                    st.error(str(error))
    with postcall:
        st.caption('Post-call summary and QA coaching evidence. All ten checklist items require employee review.')
        matching_audio=approved_cached_audio(con,case_id.strip())
        for audio_body in matching_audio:
            with st.expander('Local audio transcription: '+audio_body['voice_sample_id']):
                st.caption('Mixed speakers are unassigned. Verify the recording and copy only confirmed customer statements into conversation assistance.')
                audio_path=safe_file(DEFAULT_RELEASE,audio_body['file_path'])
                if audio_path.exists():
                    st.audio(str(audio_path))
                st.json(audio_body['segments'])
                st.caption('Pretrained '+audio_body['model']+' · CPU int8 · Speaker attribution requires employee review')
        if st.button('Review latest matched call'):
            try:
                st.session_state['post_call']=post_call(con,case_id.strip(),when=when)
            except ValueError as error:
                st.error(str(error))
        call=st.session_state.get('post_call')
        if call and call['case_id']==case_id.strip() and call.get('review_cutoff')==when.isoformat():
            st.write(call['summary'])
            st.caption('Recorded call: '+str(call.get('call_start_ts','unknown'))+' · Reviewed as of '+call['review_cutoff'])
            structured=call.get('structured_summary')
            if structured:
                for key,title in [('customer_situation','Customer situation'),('commitments','Explicit customer commitments'),('unresolved_issues','Unresolved issues'),('follow_ups','Follow-ups and context')]:
                    st.subheader(title)
                    if structured.get(key):
                        st.dataframe(structured[key],hide_index=True)
                    else:
                        st.caption('No qualifying evidence extracted. Confirm against the recording.')
                for limitation in structured.get('extraction_limits',[]):
                    st.caption(limitation)
            issue_count=sum(item['status']=='potential_issue' for item in call['qa'])
            if issue_count:
                st.warning(str(issue_count)+' checklist item(s) have potential issues. Review their evidence first; these are detector candidates, not confirmed violations.')
            for item in sorted(call['qa'],key=lambda item:item['status']!='potential_issue'):
                with st.expander(item['item_code']+': '+item['status']):
                    st.write(item['reason'])
                    if item.get('critical_flag'):
                        st.caption('Critical checklist item. Employee evidence review required.')
                    if item.get('applicability'):
                        st.caption('Applicability: '+str(item['applicability']))
                    if item.get('observations'):
                        st.json(item['observations'])
                    st.json(item['evidence'])
            for limitation in call['limitations']:
                st.caption(limitation)
            with st.form('call_review:'+case_id.strip()+':'+call['transcript_id']):
                outcomes={'Not reviewed':'not_reviewed','Meets criterion':'meets_criterion','Issue observed':'issue_observed','Not applicable':'not_applicable','Cannot determine':'cannot_determine'}
                observations={}
                with st.expander('Employee checklist observations'):
                    st.caption('Choose outcomes after reviewing the recording and policy. Add evidence timestamps or explain applicability. These observations do not execute an action or certify compliance.')
                    for item in call['qa']:
                        code=item['item_code']
                        outcome=st.selectbox(code,list(outcomes),key='qa_outcome:'+case_id.strip()+':'+call['transcript_id']+':'+code)
                        note=st.text_input('Evidence or applicability: '+code,max_chars=1200,key='qa_note:'+case_id.strip()+':'+call['transcript_id']+':'+code)
                        observations[code]={'outcome':outcomes[outcome],'note':note}
                call_decision=st.radio('Post-call review decision',['accept','edit','reject'],horizontal=True)
                call_edit=st.text_area('Edited post-call note or coaching')
                call_reason=st.text_area('Post-call review reason')
                call_submit=st.form_submit_button('Record post-call review')
            if call_submit:
                try:
                    reviewed_call=reviewed_checklist(call,observations)
                    review_id=save_review(actor['name'] if USERS.exists() else reviewer.strip(),reviewed_call,call_decision,call_edit,call_reason)
                    st.success('Post-call review recorded: '+review_id)
                except ValueError as error:
                    st.error(str(error))
    with review:
        st.subheader('Case brief')
        brief_key=json.dumps(brief,sort_keys=True,default=str)
        config=settings()
        if LOCAL_MODEL.exists():
            if st.button('Draft local AI summary from approved facts'):
                try:
                    with st.spinner('Running local model and checking evidence...'):
                        st.session_state['ai_brief']=(brief_key,enhance_local_summary(bundle,brief))
                except ValueError as error:
                    st.error(str(error))
        if trained_available():
            if st.button('Draft with the locally fine-tuned model'):
                try:
                    with st.spinner('Running the local GPU adapter and verifying required facts...'):
                        st.session_state['ai_brief']=(brief_key,enhance_trained_summary(bundle,brief))
                except ValueError as error:
                    st.error(str(error))
        if config['OPENAI_API_KEY'] and config['OPENAI_MODEL']:
            if st.button('Draft AI summary from approved facts'):
                try:
                    with st.spinner('Drafting and checking cited evidence...'):
                        st.session_state['ai_brief']=(brief_key,enhance_summary(bundle,brief))
                except ValueError as error:
                    st.error(str(error))
        else:
            st.caption('The case brief is ready. Optional paid drafting needs an API key and model setting.')
        saved=st.session_state.get('ai_brief')
        if saved and saved[0]==brief_key:
            brief=saved[1]
        st.write(brief['summary'])
        gate=brief['contact_gate']
        if gate['eligible']:
            st.success('Proposed contact passed the demo policy checks. Employee review is still required.')
        else:
            st.warning('Contact blocked: '+', '.join(gate['reasons']))
        st.write(brief['proposed_step'])
        with st.expander('Sources and policy checks'):
            st.json({'sources':brief['sources'],'contact_gate':gate})
        with st.form('review_form'):
            decision=st.radio('Review decision',['accept','edit','reject'],horizontal=True)
            edited=st.text_area('Edited assistance step')
            reason=st.text_area('Reason or review notes')
            submitted=st.form_submit_button('Record review')
        if submitted:
            try:
                review_id=save_review(actor['name'] if USERS.exists() else reviewer.strip(),brief,decision,edited,reason)
                st.success('Review recorded: '+review_id+'. No action was executed.')
            except ValueError as error:
                st.error(str(error))
    with questions:
        st.caption('Supported examples: average DPD by queue; open cases by bucket; promise-kept rate in August 2026; contact frequency; hardship policy; recorded call summary for a case.')
        question=st.text_input('Collections question',value='How many collections cases are open today, by current bucket?')
        if st.button('Answer with evidence'):
            try:
                result=answer(con,question,actor=actor)
                (st.warning if result['refused'] else st.write)(result['answer'])
                with st.expander('SQL or sources',expanded=True):
                    st.code(result['sql_or_sources'])
            except Exception:
                st.error('The source query failed. No answer was guessed; employee review is required.')
