"""Paired study validation with explicitly artificial test observations."""
import csv
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import duckdb
from preparation_study import assignments,analyze_rows,prepare


def manifest():
    return {'participants':['P01','P02'],'pairs':[{'pair_id':'PAIR-'+str(i),
        'cases':[{'case_id':'CASE-'+str(2*i+j),'golden_customer_id':'CUSTOMER-'+str(2*i+j)} for j in range(2)]} for i in range(4)]}


def artificial_observations(source):
    return [{**r,'elapsed_seconds':120 if r['mode']=='manual' else 60,
             'correct_items':6,'unsafe_accepted':'false'} for r in assignments(source)]


class PreparationStudyChecks(unittest.TestCase):
    def test_counterbalance_and_paired_analysis(self):
        source=manifest();rows=artificial_observations(source)
        for case in [c['case_id'] for p in source['pairs'] for c in p['cases']]:
            self.assertEqual({r['mode'] for r in rows if r['case_id']==case},{'manual','assisted'})
        result=analyze_rows(source,rows)
        self.assertEqual(result['tasks'],16)
        self.assertEqual(result['paired_comparisons'],8)
        self.assertEqual(result['all_task_median_improvement_pct'],50)
        rows[0]['correct_items']=5;rows[1]['unsafe_accepted']='true'
        result=analyze_rows(source,rows)
        self.assertEqual(sum(m['correct_complete_tasks'] for m in result['modes'].values()),14)
        self.assertEqual(sum(m['incorrect_items'] for m in result['modes'].values()),1)
        self.assertEqual(sum(m['unsafe_accepted_tasks'] for m in result['modes'].values()),1)

    def test_rejects_unobserved_incomplete_duplicate_and_confounded_tasks(self):
        source=manifest();valid=artificial_observations(source)
        invalid=[assignments(source),valid[:-1]]
        duplicate=deepcopy(valid);duplicate[-1]=deepcopy(duplicate[0]);invalid.append(duplicate)
        wrong=deepcopy(valid);wrong[0]['case_id']=wrong[1]['case_id'];invalid.append(wrong)
        for field,value in [('elapsed_seconds',0),('elapsed_seconds',float('nan')),
                            ('correct_items',7),('unsafe_accepted','unknown')]:
            rows=deepcopy(valid);rows[0][field]=value;invalid.append(rows)
        for rows in invalid:
            with self.assertRaises(ValueError):analyze_rows(source,rows)
        reused=manifest();reused['pairs'][1]['cases'][0]=reused['pairs'][0]['cases'][0]
        with self.assertRaises(ValueError):assignments(reused)

    def test_prepare_uses_approved_open_distinct_customers_and_never_fills_observations(self):
        with tempfile.TemporaryDirectory() as folder:
            database=Path(folder)/'cases.duckdb';output=Path(folder)/'study'
            with duckdb.connect(str(database)) as con:
                con.execute('CREATE SCHEMA curated; CREATE TABLE curated.cases(case_id VARCHAR,golden_customer_id VARCHAR,queue VARCHAR,current_bucket VARCHAR,total_overdue_cad DECIMAL(18,2),current_dpd INTEGER,case_status VARCHAR)')
                for i in range(8):
                    con.execute("INSERT INTO curated.cases VALUES (?,?,'early','1-30',?,10,'open')",['CASE-'+str(i),'CUSTOMER-'+str(i),100+i])
                con.execute("INSERT INTO curated.cases VALUES ('CLOSED','CLOSED-CUSTOMER','early','1-30',100,10,'closed')")
            self.assertEqual(prepare(database,output)['blank_rows'],16)
            with (output/'results.csv').open() as handle:rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),16)
            self.assertTrue(all(r['elapsed_seconds']==r['correct_items']==r['unsafe_accepted']=='' for r in rows))
            self.assertNotIn('CLOSED',{r['case_id'] for r in rows})
            with self.assertRaises(FileExistsError):prepare(database,output)


if __name__=='__main__':unittest.main()
