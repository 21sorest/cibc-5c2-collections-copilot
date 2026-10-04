"""Regression for duplicate classifier inputs hidden by changing numeric values."""
import unittest
from train_classifier import grouped_split, tokens
from text_signals import normalize, redact


class ClassifierSplitChecks(unittest.TestCase):
    def test_numeric_template_variants_stay_in_one_partition(self):
        rows=[{'id':str(i),'customer':str(i),'text':'Unique statement '+chr(97+i)} for i in range(30)]
        rows[0]['text']='Payment of 100 is due on 2026-09-28'
        rows[1]['text']='Payment of 250 is due on 2026-09-28'
        self.assertNotEqual(normalize(redact(rows[0]['text'])),normalize(redact(rows[1]['text'])))
        self.assertEqual(tokens(rows[0]['text']),tokens(rows[1]['text']))
        train,test,_=grouped_split(rows)
        self.assertTrue(train and test)
        partitions={row['id']:name for name,group in [('train',train),('test',test)] for row in group}
        self.assertEqual(partitions['0'],partitions['1'])
        self.assertFalse({tuple(sorted(tokens(row['text']))) for row in train}&
                         {tuple(sorted(tokens(row['text']))) for row in test})


if __name__=='__main__':
    unittest.main()
