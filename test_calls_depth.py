"""Independent chronology, commitment and privacy examples for post-call employee review."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
from calls import qa_evidence,structured_call_summary,post_call


def turn(speaker,stamp,text):
    return {'speaker':speaker,'start_sec':stamp,'text':text}


class CallsDepthChecks(unittest.TestCase):
    def test_customer_commitments_require_own_amount_and_date_not_agent_offer_or_yes(self):
        turns=[turn('agent',1,'Your account is past due.'),turn('agent',2,'Can you pay $100 tomorrow?'),
            turn('customer',3,'Yes, that works.'),turn('customer',4,"If I get paid, I will pay $100 tomorrow."),
            turn('customer',5,'I will pay $25 on 2026-09-29.'),turn('customer',6,'I will pay $50 next Friday.'),
            turn('customer',7,'My salary is $1200 and I will pay $100 tomorrow.'),
            turn('customer',8,'I will pay $100 tomorrow or next Friday.')]
        result=structured_call_summary(turns)
        self.assertEqual([item['amount_text'] for item in result['commitments']],['$25','$50'])
        self.assertEqual(result['commitments'][0]['date_text'],'2026-09-29')
        self.assertEqual(result['commitments'][1]['date_text'],'next friday')
        self.assertTrue(all(item['requires_employee_confirmation'] for item in result['commitments']))
        self.assertTrue(any(item['kind']=='payment proposal needs confirmation' for item in result['follow_ups']))

    def test_verification_and_protected_context_do_not_enter_new_summary(self):
        turns=[turn('agent',1,'Before discussing your account, confirm your date of birth.'),
            turn('customer',2,'July 8, 1992.'),turn('agent',3,'Your balance is past due.'),
            turn('customer',4,'I am a woman and my hours were cut.'),turn('agent',5,'I will send you a payment link.')]
        result=structured_call_summary(turns)
        text=json.dumps(result)
        self.assertNotIn('1992',text)
        self.assertNotIn('I am a woman',text)
        self.assertIn('hardship',text)
        self.assertTrue(result['follow_ups'])

    def test_customer_capacity_terms_are_pending_proposals_and_past_payment_is_not(self):
        turns=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I can do $125 on September 28.'),
            turn('customer',3,'I paid $100 on September 20.')]
        result=structured_call_summary(turns)
        self.assertFalse(result['commitments'])
        proposals=[item for item in result['follow_ups'] if item['kind']=='payment proposal needs confirmation']
        self.assertEqual(len(proposals),1)
        self.assertEqual(proposals[0]['amount_text'],'$125')
        self.assertEqual(proposals[0]['date_text'],'september 28')
        self.assertFalse(proposals[0]['confirmed_commitment'])

    def test_negated_quoted_and_third_party_intent_does_not_become_commitment(self):
        statements=['I cannot promise that I will pay $100 on Friday.',
            'My spouse said I will pay $100 on Friday.',
            '"I will pay $100 on Friday" is what my spouse said.',
            'If I receive my salary, I will pay $100 on Friday.',
            'I will pay $100 on Friday, but I cannot guarantee it.',
            'I cannot pay today. I will pay $100 on Friday.']
        for text in statements:
            with self.subTest(text=text):
                result=structured_call_summary([turn('agent',1,'Your account is past due.'),turn('customer',2,text)])
                self.assertFalse(result['commitments'])
        actual=structured_call_summary([turn('agent',1,'Your account is past due.'),turn('customer',2,'Okay, I will pay $100 on Friday.')])
        self.assertEqual(len(actual['commitments']),1)

    def test_hardship_acknowledgment_and_options_must_precede_payment_request(self):
        base=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I lost my job.')]
        unsafe=base+[turn('agent',3,'Can you pay the amount today?'),turn('agent',4,'Sorry to hear that. We have a reduced payment option.')]
        safe=base+[turn('agent',3,'Sorry to hear that. We have a reduced payment option.'),turn('agent',4,'Can you pay an affordable amount today?')]
        for turns,expected in [(unsafe,'potential_issue'),(safe,'evidence_found')]:
            row={row['item_code']:row for row in qa_evidence(turns)}['hardship_handled_per_policy']
            self.assertEqual(row['status'],expected)
            self.assertTrue(row['needs_source_verification'])
            self.assertFalse(row['automatic_compliance_verdict'])

    def test_ptp_readback_is_customer_grounded_and_different_amount_is_flagged(self):
        base=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I will pay $100 tomorrow.')]
        mismatch=base+[turn('agent',3,'Just to confirm, a payment of $10 tomorrow.')]
        match=base+[turn('agent',3,'Just to confirm, a payment of $100.00 tomorrow.')]
        for turns,expected in [(mismatch,'potential_issue'),(match,'evidence_found')]:
            row={row['item_code']:row for row in qa_evidence(turns)}['ptp_details_confirmed_back']
            self.assertEqual(row['status'],expected)
        unresolved=base+[turn('agent',3,'Just to confirm, a payment of $100 on September 28.')]
        row={row['item_code']:row for row in qa_evidence(unresolved)}['ptp_details_confirmed_back']
        self.assertEqual(row['status'],'needs_review')
        self.assertEqual(row['observations']['unresolved_date_readbacks'],1)
        assent=[turn('agent',1,'Your account is past due. Can you pay $100 tomorrow?'),turn('customer',2,'Yes.'),
            turn('agent',3,'Just to confirm, a payment of $100 tomorrow.')]
        self.assertEqual({row['item_code']:row for row in qa_evidence(assent)}['ptp_details_confirmed_back']['status'],'applicability_needs_review')

    def test_payment_method_request_and_same_turn_before_transfer_are_ordered(self):
        turns=[turn('agent',1,'Your account is past due.'),turn('customer',2,'My hours were cut.'),
            turn('agent',3,'How would you like to make that payment?')]
        rows={row['item_code']:row for row in qa_evidence(turns)}
        self.assertEqual(rows['hardship_handled_per_policy']['status'],'potential_issue')
        turns=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I need an arrangement.'),
            turn('agent',3,'Before I transfer you, we can also set up a payment plan.')]
        rows={row['item_code']:row for row in qa_evidence(turns)}
        self.assertEqual(rows['options_offered_before_escalation']['status'],'evidence_found')
        self.assertTrue(rows['options_offered_before_escalation']['observations']['same_turn_before_transfer_wording'])

    def test_same_turn_hardship_and_identity_order_uses_text_offsets(self):
        turns=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I lost my job.'),
            turn('agent',3,'Can you pay today? Sorry to hear that. We have a reduced payment option.')]
        row={row['item_code']:row for row in qa_evidence(turns)}['hardship_handled_per_policy']
        self.assertEqual(row['status'],'potential_issue')
        self.assertFalse(row['observations']['same_turn_order_unknown'])
        turns=[turn('agent',1,'Your past due balance is $100. Please confirm your date of birth.'),turn('customer',2,'[PII]')]
        row={row['item_code']:row for row in qa_evidence(turns)}['identity_verified_before_disclosure']
        self.assertEqual(row['status'],'potential_issue')
        self.assertFalse(row['observations']['same_turn_order_unknown'])

    def test_all_ten_items_distinguish_unknown_and_observable_ordering(self):
        turns=[turn('agent',1,'Your past due balance is $100.'),turn('agent',2,'This call may be recorded.'),
            turn('agent',3,'Please confirm your date of birth.'),turn('customer',4,'[PII]')]
        rows={row['item_code']:row for row in qa_evidence(turns)}
        self.assertEqual(len(rows),10)
        self.assertEqual(rows['recording_notice_given']['status'],'potential_issue')
        self.assertEqual(rows['identity_verified_before_disclosure']['status'],'potential_issue')
        self.assertEqual(rows['fees_and_balance_stated_accurately']['status'],'needs_review')
        self.assertEqual(rows['no_threatening_language']['status'],'needs_review')
        self.assertEqual(rows['agent_identified_self_and_purpose']['status'],'needs_review')
        self.assertTrue(rows['no_threatening_language']['critical_flag'])
        self.assertTrue(all(row['checklist_version']=='QA-2026.2' for row in rows.values()))

    def test_french_customer_commitment_and_negated_threat_are_reviewed(self):
        turns=[turn('agent',1,'Votre compte est en souffrance.'),turn('customer',2,'Je vais payer 100 dollars demain.'),
            turn('agent',3,'Nous ne pouvons pas vous arrêter.'),turn('agent',4,'Pour confirmer, un paiement de 100 dollars demain.')]
        self.assertEqual(structured_call_summary(turns)['commitments'][0]['date_text'],'demain')
        rows={row['item_code']:row for row in qa_evidence(turns)}
        self.assertEqual(rows['no_threatening_language']['status'],'needs_review')
        self.assertEqual(rows['ptp_details_confirmed_back']['status'],'evidence_found')

    def test_within_turn_ack_option_then_request_is_ordered_and_demand_is_detected(self):
        base=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I lost my job.')]
        for text,expected in [
            ('Sorry to hear that. We have a reduced payment option. Can you pay today?','evidence_found'),
            ('I understand, but the full amount is still due.','potential_issue'),
            ('Can you pay today? We have options. Sorry to hear that.','potential_issue')]:
            row={x['item_code']:x for x in qa_evidence(base+[turn('agent',3,text)])}['hardship_handled_per_policy']
            self.assertEqual(row['status'],expected)
        identity=[turn('agent',1,'Confirm your date of birth. Your balance is past due.'),turn('customer',2,'[PII]')]
        row={x['item_code']:x for x in qa_evidence(identity)}['identity_verified_before_disclosure']
        self.assertEqual(row['status'],'needs_review')

    def test_proposal_readback_and_latest_revision_do_not_create_commitments(self):
        base=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I can do $100 on Friday.')]
        row={x['item_code']:x for x in qa_evidence(base+[turn('agent',3,'Just to confirm, a payment of $10 on Friday.')])}['ptp_details_confirmed_back']
        self.assertEqual(row['status'],'needs_review')
        self.assertEqual(row['observations']['explicit_customer_commitments'],0)
        self.assertEqual(row['observations']['proposal_mismatching_readbacks'],1)
        self.assertTrue(row['needs_source_verification'])
        revised=base+[turn('customer',3,'I can do $50 on Friday.'),turn('agent',4,'Just to confirm, a payment of $50 on Friday.')]
        row={x['item_code']:x for x in qa_evidence(revised)}['ptp_details_confirmed_back']
        self.assertEqual(row['status'],'needs_review')
        self.assertEqual(row['observations']['proposal_matching_readbacks'],1)
        self.assertFalse(structured_call_summary(revised)['commitments'])
        ambiguous=base+[turn('agent',3,'Just to confirm, either $100 or $50 on Friday.')]
        row={x['item_code']:x for x in qa_evidence(ambiguous)}['ptp_details_confirmed_back']
        self.assertEqual(row['status'],'needs_review')
        self.assertEqual(row['observations']['ambiguous_readbacks'],1)

    def test_literal_month_aliases_match_without_inventing_year_or_weekday_anchor(self):
        base=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I will pay $100 on Jun 28.')]
        row={x['item_code']:x for x in qa_evidence(base+[turn('agent',3,'Just to confirm, a payment of $100 on June 28.')])}['ptp_details_confirmed_back']
        self.assertEqual(row['status'],'evidence_found')
        row={x['item_code']:x for x in qa_evidence(base+[turn('agent',3,'Just to confirm, a payment of $100 on 2026-06-28.')])}['ptp_details_confirmed_back']
        self.assertEqual(row['status'],'needs_review')

    def test_locale_ambiguous_money_is_not_guessed(self):
        turns=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I can do 100,50 dollars on Friday.'),
            turn('agent',3,'Just to confirm, a payment of $100.50 on Friday.')]
        row={x['item_code']:x for x in qa_evidence(turns)}['ptp_details_confirmed_back']
        self.assertEqual(row['status'],'needs_review')
        self.assertEqual(row['observations']['ambiguous_readbacks'],1)

    def test_distinct_tied_turns_use_source_order_before_text_offsets(self):
        base=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I lost my job.')]
        safe=base+[turn('agent',3,'Some opening words. Sorry to hear that. We have options.'),turn('agent',3,'Can you pay today?')]
        unsafe=base+[turn('agent',3,'Some opening words. Can you pay today?'),turn('agent',3,'Sorry to hear that. We have options.')]
        for turns,expected in [(safe,'evidence_found'),(unsafe,'potential_issue')]:
            row={x['item_code']:x for x in qa_evidence(turns)}['hardship_handled_per_policy']
            self.assertEqual(row['status'],expected)
            self.assertTrue(row['observations']['source_chronology_monotonic'])
            self.assertEqual(sum(item['start_sec']==3 for item in row['evidence']),2)
        identity=[turn('agent',1,'Please confirm your date of birth.'),turn('agent',1,'Your balance is past due.')]
        row={x['item_code']:x for x in qa_evidence(identity)}['identity_verified_before_disclosure']
        self.assertEqual(row['status'],'needs_review')

    def test_backwards_source_timestamps_do_not_establish_safe_or_unsafe_order(self):
        turns=[turn('agent',1,'Your account is past due.'),turn('customer',4,'I lost my job.'),
            turn('agent',3,'Sorry to hear that. We have options.'),turn('agent',5,'Can you pay today?')]
        row={x['item_code']:x for x in qa_evidence(turns)}['hardship_handled_per_policy']
        self.assertEqual(row['status'],'needs_review')
        self.assertFalse(row['observations']['source_chronology_monotonic'])

    def test_retracted_terms_cannot_ground_a_later_readback(self):
        turns=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I will pay $100 on Friday.'),
            turn('customer',3,'I cannot pay that after all.'),turn('agent',4,'Just to confirm, a payment of $100 on Friday.')]
        summary=structured_call_summary(turns)
        self.assertFalse(summary['commitments'])
        self.assertTrue(any(item['kind']=='customer withdrew payment terms' for item in summary['follow_ups']))
        row={x['item_code']:x for x in qa_evidence(turns)}['ptp_details_confirmed_back']
        self.assertEqual(row['status'],'applicability_needs_review')
        revised=turns[:3]+[turn('customer',4,'I can do $50 on Friday.'),turn('agent',5,'Just to confirm, a payment of $50 on Friday.')]
        row={x['item_code']:x for x in qa_evidence(revised)}['ptp_details_confirmed_back']
        self.assertEqual(row['observations']['proposal_matching_readbacks'],1)

    def test_negated_payment_demands_do_not_create_hardship_issue(self):
        base=[turn('agent',1,'Your account is past due.'),turn('customer',2,'I lost my job.')]
        for text in ['You do not have to pay today.','You do not need to pay today.',
            'You never have to pay the full amount now.','Vous ne devez pas payer maintenant.']:
            row={x['item_code']:x for x in qa_evidence(base+[turn('agent',3,text)])}['hardship_handled_per_policy']
            self.assertNotEqual(row['status'],'potential_issue',text)
            self.assertIsNone(row['observations']['payment_request_sec'])
        mixed=base+[turn('agent',3,'You do not have to pay today. But you must pay now.')]
        row={x['item_code']:x for x in qa_evidence(mixed)}['hardship_handled_per_policy']
        self.assertEqual(row['status'],'potential_issue')

    def test_malformed_source_turns_fail_closed_with_safe_error(self):
        malformed=[None,{},turn('customer',float('nan'),'secret'),turn('agent',-1,'secret'),
            turn('customer',1,None),turn('unknown',1,'secret'),turn('agent',True,'secret')]
        for item in malformed:
            for function in (qa_evidence,structured_call_summary):
                with self.subTest(item=item,function=function.__name__),self.assertRaisesRegex(ValueError,'Malformed call evidence'):
                    function([item])

    def test_duplicate_source_turns_are_not_counted_as_two_commitments(self):
        item=turn('customer',2,'I will pay $100 tomorrow.')
        with self.assertRaisesRegex(ValueError,'duplicate source turn'):
            structured_call_summary([turn('agent',1,'Your account is past due.'),item,item.copy()])
        backwards=[turn('agent',1,'Your account is past due.'),turn('customer',3,'I will pay $100 tomorrow.'),
            turn('agent',2,'Just to confirm, $100 tomorrow.')]
        self.assertFalse(structured_call_summary(backwards)['commitments'])

    def test_known_third_party_turn_cannot_create_customer_commitment(self):
        turns=[turn('agent',1,'Your account is past due.'),turn('third_party',2,'I will pay $100 tomorrow.')]
        self.assertFalse(structured_call_summary(turns)['commitments'])
        self.assertFalse(structured_call_summary(turns)['customer_situation'])

    def test_latest_call_is_selected_at_the_aware_review_cutoff(self):
        with tempfile.TemporaryDirectory() as directory,duckdb.connect() as con:
            root=Path(directory)
            (root/'files/calls').mkdir(parents=True)
            con.execute('CREATE SCHEMA curated; CREATE TABLE curated.transcripts(case_id VARCHAR,transcript_id VARCHAR,file_path VARCHAR,call_start_ts TIMESTAMP)')
            for identifier,stamp in [('OLD','2026-09-10 12:00:00'),('NEW','2026-09-20 12:00:00')]:
                path='calls/'+identifier+'.json'
                (root/'files'/path).write_text(json.dumps({'turns':[turn('agent',1,'Your account is past due.'),turn('customer',2,'I lost my job.')]}),encoding='utf-8')
                con.execute('INSERT INTO curated.transcripts VALUES (?,?,?,?)',['CASE1',identifier,path,stamp])
            when=datetime(2026,9,15,tzinfo=timezone.utc)
            result=post_call(con,'CASE1',root,when=when)
            self.assertEqual(result['transcript_id'],'OLD')
            self.assertEqual(result['review_cutoff'],when.isoformat())
            self.assertIn('2026-09-10',result['call_start_ts'])
            self.assertEqual(post_call(con,'CASE1',root)['transcript_id'],'NEW')
            with self.assertRaises(ValueError):
                post_call(con,'CASE1',root,when=datetime(2026,9,15))


if __name__=='__main__':
    unittest.main()
