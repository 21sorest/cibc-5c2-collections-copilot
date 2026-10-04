"""Existing local review histories must remain verifiable before an append."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from assistant import save_review,verify_review_log


class ReviewIntegrityChecks(unittest.TestCase):
    def test_valid_log_and_tampered_payload_prevent_append_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'reviews.sqlite'
            self.assertTrue(verify_review_log(path)['valid'])
            self.assertFalse(path.exists())
            save_review('AG1',{'case_id':'CASE1','summary':'Original'},'accept',audit_path=path)
            save_review('AG1',{'case_id':'CASE1','summary':'Second'},'reject',audit_path=path)
            report=verify_review_log(path)
            self.assertTrue(report['valid'])
            self.assertEqual(report['reviews_checked'],2)
            with closing(sqlite3.connect(path)) as db,db:
                payload=json.loads(db.execute('SELECT payload FROM reviews WHERE sequence=1').fetchone()[0])
                payload['brief']['summary']='Changed after employee review'
                db.execute('UPDATE reviews SET payload=? WHERE sequence=1',[json.dumps(payload,sort_keys=True)])
            self.assertFalse(verify_review_log(path)['valid'])
            with self.assertRaisesRegex(ValueError,'integrity check failed'):
                save_review('AG1',{'case_id':'CASE1','summary':'Third'},'accept',audit_path=path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM reviews').fetchone()[0],2)


if __name__=='__main__':
    unittest.main()
