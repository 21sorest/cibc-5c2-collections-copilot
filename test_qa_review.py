"""Employee checklist observations stay separate from automatic detector output."""
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
import unittest

from assistant import reviewed_checklist, save_review, verify_review_log


class ChecklistReviewChecks(unittest.TestCase):
    def setUp(self):
        self.call={'case_id':'CASE1','transcript_id':'T1','requires_human_review':True,
            'qa':[{'item_code':str(i),'status':'needs_review'} for i in range(10)]}
        self.observations={str(i):{'outcome':'not_reviewed','note':''} for i in range(10)}

    def test_unknown_is_not_pass_and_employee_evidence_is_required(self):
        result=reviewed_checklist(self.call,self.observations)
        self.assertEqual(result['checklist_reviewed_count'],0)
        self.observations['0']={'outcome':'meets_criterion','note':''}
        with self.assertRaises(ValueError):
            reviewed_checklist(self.call,self.observations)
        self.observations['0']={'outcome':'meets_criterion','note':'Notice at 3s before account discussion.'}
        result=reviewed_checklist(self.call,self.observations)
        self.assertEqual(result['checklist_reviewed_count'],1)
        self.assertEqual(result['qa'],self.call['qa'])
        self.assertNotIn('employee_checklist',self.call)
        for value in ({}, {**self.observations,'other':{'outcome':'not_reviewed'}}):
            with self.assertRaises(ValueError):
                reviewed_checklist(self.call,value)

    def test_observations_bind_to_transcript_in_verified_audit(self):
        self.observations['1']={'outcome':'issue_observed','note':'Disclosure at 4s; identity prompt at 9s.'}
        call=reviewed_checklist(self.call,self.observations)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'reviews.sqlite'
            save_review('reviewer',call,'accept',audit_path=path)
            self.assertTrue(verify_review_log(path)['valid'])
            with closing(sqlite3.connect(path)) as db:
                payload=json.loads(db.execute('SELECT payload FROM reviews').fetchone()[0])
            self.assertEqual(payload['brief']['transcript_id'],'T1')
            self.assertEqual(payload['brief']['employee_checklist']['1']['outcome'],'issue_observed')
            self.assertFalse(payload['executed'])


if __name__=='__main__':
    unittest.main()
