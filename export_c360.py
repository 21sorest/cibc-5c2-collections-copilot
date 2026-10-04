"""Prepare a reproducible local C360 package for user-managed Hugging Face publication."""
import hashlib
import json
import shutil

import duckdb
from pipeline import ROOT, sql_literal


def export():
    destination=ROOT/'data/c360_release'
    destination.mkdir(parents=True,exist_ok=True)
    parquet=destination/'c360.parquet'
    with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
        con.execute('COPY (SELECT * FROM golden.c360 ORDER BY golden_customer_id) TO '+sql_literal(parquet)+' (FORMAT PARQUET, COMPRESSION ZSTD)')
        rows=con.execute('SELECT count(*) FROM golden.c360').fetchone()[0]
        assert con.execute('SELECT count(*) FROM read_parquet(?)',[str(parquet)]).fetchone()[0]==rows
    digest=hashlib.sha256()
    with parquet.open('rb') as handle:
        while block:=handle.read(1024*1024):
            digest.update(block)
    manifest={'snapshot_date':'2026-09-28','rows':rows,'file':'c360.parquet',
        'sha256':digest.hexdigest(),'bytes':parquet.stat().st_size,
        'generator':'python export_c360.py','source_dataset':'https://huggingface.co/datasets/nuxsh/maple-collections-hackathon',
        'synthetic':True,'publication_status':'local package only; no upload performed'}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    shutil.copyfile(ROOT/'contracts/c360.json',destination/'c360_contract.json')
    shutil.copyfile(ROOT/'reports/data_quality.md',destination/'data_quality.md')
    (destination/'README.md').write_text('''---
pretty_name: Team 5C2 synthetic Collections C360
language:
- en
task_categories:
- tabular-classification
---
# Synthetic Collections C360

Generated from the Maple Bank hackathon release dated 28 September 2026. One accepted golden customer per snapshot, with independent account aggregation and explicit coverage/missingness. This is synthetic data, not a real bank customer dataset.

See c360_contract.json for schema, owner, quality rules, permitted uses and limitations. See data_quality.md for measured quarantine and matching counts. Check manifest.json for row count and SHA256 before use.

Reproduce using the project repository: python pipeline.py build, then python export_c360.py. This package contains no raw names, phones, DOB, addresses, protected attributes or raw notes. Financial information and golden IDs are synthetic. No outcome prediction or historical point-in-time training claim is made.

The original dataset licensing/redistribution terms must be checked before publication. No new license is asserted by this generated card. Add the project repository URL and final upload link after account setup.
''',encoding='utf-8')
    (ROOT/'reports/c360_export.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    export()
