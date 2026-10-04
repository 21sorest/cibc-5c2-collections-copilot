"""UI checks for real login, assignment scope and reviewed conversation drafts."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import duckdb
from streamlit.testing.v1 import AppTest
import access
import assistant
from pipeline import ROOT


@unittest.skipUnless((ROOT/'data/collections.duckdb').exists(),'Local UI integration needs the built synthetic dataset')
class LocalUIChecks(unittest.TestCase):
    def test_decision_and_structured_call_review_with_employee_checklist(self):
        with tempfile.TemporaryDirectory() as directory:
            registry=Path(directory)/'users.json'
            audit=Path(directory)/'reviews.sqlite'
            access.add_user('test-supervisor','temporary-test-password','supervisor',path=registry)
            read_users=access.users
            authenticate=access.authenticate
            save=assistant.save_review
            with patch('access.USERS',registry),patch('access.users',side_effect=lambda *args:read_users(registry)),patch('access.authenticate',side_effect=lambda u,p:authenticate(u,p,registry)),patch('assistant.save_review',side_effect=lambda *args:save(*args,audit_path=audit)):
                ui=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
                next(x for x in ui.text_input if x.label=='Username').set_value('test-supervisor')
                next(x for x in ui.text_input if x.label=='Password').set_value('temporary-test-password')
                next(x for x in ui.button if x.label=='Sign in').click()
                ui.run(timeout=30)
                next(x for x in ui.button if x.label=='Compare action, channels and routing').click()
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                self.assertIn('routing_requirements',ui.session_state['decision_proposal'])
                next(x for x in ui.text_input if x.label=='Case ID').set_value('CS-2026-942626')
                ui.run(timeout=30)
                next(x for x in ui.button if x.label=='Review latest matched call').click()
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                call=ui.session_state['post_call']
                self.assertIn('structured_summary',call)
                code=call['qa'][0]['item_code']
                next(x for x in ui.selectbox if x.label==code).set_value('Cannot determine')
                next(x for x in ui.text_input if x.label=='Evidence or applicability: '+code).set_value('Verification success needs recording review.')
                next(x for x in ui.button if x.label=='Record post-call review').click()
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                self.assertTrue(any('Post-call review recorded' in x.value for x in ui.success))
                self.assertTrue(assistant.verify_review_log(audit)['valid'])
                next(x for x in ui.text_input if x.label=='Case ID').set_value('CS-2026-614370')
                ui.run(timeout=30)
                self.assertFalse(any(x.label=='Record post-call review' for x in ui.button))

    def test_agent_login_and_case_scope(self):
        with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
            agent=con.execute("SELECT assigned_agent_id FROM curated.cases WHERE case_status='open' AND assigned_agent_id IS NOT NULL GROUP BY 1 HAVING count(*)>1 LIMIT 1").fetchone()[0]
        with tempfile.TemporaryDirectory() as directory:
            registry=Path(directory)/'users.json'
            access.add_user('test-employee','temporary-test-password','agent',agent,registry)
            read_users=access.users
            authenticate=access.authenticate
            with patch('access.USERS',registry),patch('access.users',side_effect=lambda *args:read_users(registry)),patch('access.authenticate',side_effect=lambda u,p:authenticate(u,p,registry)):
                ui=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
                self.assertFalse(ui.exception)
                next(x for x in ui.text_input if x.label=='Username').set_value('test-employee')
                next(x for x in ui.text_input if x.label=='Password').set_value('temporary-test-password')
                next(x for x in ui.button if x.label=='Sign in').click()
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                self.assertTrue(any(x.label=='Assigned case' for x in ui.selectbox))
                self.assertFalse(any(x.label=='Case ID' for x in ui.text_input))
                self.assertTrue(next(x for x in ui.text_input if x.label=='Reviewer name or employee ID').disabled)
                next(x for x in ui.text_area if x.label=='What did the customer say?').set_value('I lost my job; please call me back tomorrow')
                next(x for x in ui.checkbox if x.label=='Employee completed approved identity verification').check()
                next(x for x in ui.button if x.label=='Prepare conversation assistance').click()
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                self.assertTrue(ui.session_state['conversation_draft']['signals']['hardship'])
                self.assertTrue(ui.session_state['conversation_draft']['requires_human_review'])
                assigned=next(x for x in ui.selectbox if x.label=='Assigned case')
                first_case=assigned.value
                self.assertGreater(len(assigned.options),1)
                if len(assigned.options)>1:
                    assigned.set_value(next(value for value in assigned.options if value!=first_case))
                    ui.run(timeout=30)
                    self.assertFalse(ui.exception)
                    self.assertFalse(next(x for x in ui.checkbox if x.label=='Employee completed approved identity verification').value)
                    self.assertEqual(next(x for x in ui.text_area if x.label=='What did the customer say?').value,'')
                    self.assertFalse(any(x.label=='Record conversation review' for x in ui.button))
                selected=next(x for x in ui.selectbox if x.label=='Assigned case').value
                next(x for x in ui.text_input if x.label=='Collections question').set_value(f'Show C360 and overdue balance for {selected}')
                next(x for x in ui.button if x.label=='Answer with evidence').click()
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                self.assertTrue(any('case_overdue_cad' in x.value for x in ui.markdown))
                next(x for x in ui.text_input if x.label=='Collections question').set_value('How many golden customers are there?')
                next(x for x in ui.button if x.label=='Answer with evidence').click()
                ui.run(timeout=30)
                self.assertTrue(any('supervisor role' in x.value for x in ui.warning))
                ui.session_state['decision_proposal']={'case_id':first_case}
                ui.session_state['post_call']={'case_id':first_case}
                ui.session_state['ai_brief']=('stale',{'summary':'Old employee draft'})
                ui.session_state['login_until']=0
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                self.assertTrue(any(x.label=='Password' for x in ui.text_input))
                for key in ('actor','conversation_draft','decision_proposal','post_call','ai_brief'):
                    with self.assertRaises(KeyError):
                        ui.session_state[key]
                next(x for x in ui.text_input if x.label=='Username').set_value('test-employee')
                next(x for x in ui.text_input if x.label=='Password').set_value('temporary-test-password')
                next(x for x in ui.button if x.label=='Sign in').click()
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                registry_text=registry.read_text(encoding='utf-8')
                ui.session_state['conversation_draft']={'case_id':first_case,'summary':'Old authenticated draft'}
                registry.write_text('{}',encoding='utf-8')
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                self.assertTrue(any(x.label=='Password' for x in ui.text_input))
                with self.assertRaises(KeyError):
                    ui.session_state['conversation_draft']
                registry.write_text(registry_text,encoding='utf-8')
                next(x for x in ui.text_input if x.label=='Username').set_value('test-employee')
                next(x for x in ui.text_input if x.label=='Password').set_value('temporary-test-password')
                next(x for x in ui.button if x.label=='Sign in').click()
                ui.run(timeout=30)
                self.assertFalse(ui.exception)
                next(x for x in ui.button if x.label=='Sign out').click()
                ui.run(timeout=30)
                self.assertTrue(any(x.label=='Password' for x in ui.text_input))


if __name__=='__main__':
    unittest.main()
