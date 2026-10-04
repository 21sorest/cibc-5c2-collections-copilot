"""Build the first Collections 360 snapshot from the synthetic release."""

import argparse
import csv
from datetime import date
import json
from pathlib import Path
import time

import duckdb

ROOT = Path(__file__).resolve().parent
DEFAULT_RELEASE = ROOT / 'maple_data' / 'maple_collections_release'


def sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def register_sources(con, release):
    schema = json.loads((release / 'schema' / 'schema.json').read_text(encoding='utf-8'))
    inventory = []
    for name, metadata in schema.items():
        path = release / metadata['path']
        if metadata['format'].lower() == 'csv':
            if not path.exists():
                raise FileNotFoundError(path)
            with path.open(encoding='utf-8', newline='') as source:
                columns = next(csv.reader(source))
            expected = {column['name'] for column in metadata['columns']}
            inventory.append({'table': name, 'format': 'csv', 'declared_rows': metadata['rows'],
                              'added_columns': sorted(set(columns) - expected),
                              'missing_columns': sorted(expected - set(columns))})
            reader = f"read_csv({sql_literal(path.as_posix())}, header=true, all_varchar=true, nullstr='')"
        else:
            files = list(path.rglob('*.parquet'))
            if not files:
                raise FileNotFoundError(f'No Parquet files in {path}')
            reader = f"read_parquet({sql_literal(path.as_posix() + '/*/*.parquet')}, hive_partitioning=true)"
            inventory.append({'table': name, 'format': 'parquet', 'declared_rows': metadata['rows'],
                              'files': len(files)})
        con.execute(f'CREATE VIEW raw."{name}" AS SELECT * FROM {reader}')
    return inventory


def build(release, database, report_dir, as_of=date(2026, 9, 28)):
    """Build transactionally; preserve the previous snapshot if a check fails."""
    release, database, report_dir = Path(release).resolve(), Path(database).resolve(), Path(report_dir).resolve()
    if not release.is_dir():
        raise FileNotFoundError(release)
    database.parent.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with duckdb.connect(str(database)) as con:
        con.execute("SET memory_limit='4GB'")
        con.execute('SET threads=4')
        con.execute('BEGIN')
        try:
            # Replacing the foundation also invalidates every dependent feature snapshot.
            for schema in ('features', 'raw', 'restricted', 'curated', 'golden'):
                con.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')
                con.execute(f'CREATE SCHEMA {schema}')
            con.execute(f"SET VARIABLE snapshot_date={sql_literal(as_of.isoformat())}::DATE")
            inventory = register_sources(con, release)
            print('Raw sources registered. Building curated records and identity links...', flush=True)
            statements = con.extract_statements((ROOT / 'sql' / 'foundation.sql').read_text(encoding='utf-8'))
            for statement in statements:
                con.execute(statement)
                query = statement.query.strip()
                if query.startswith('CREATE TABLE'):
                    print(f"Built {query.split()[2]}", flush=True)
                elif query.startswith('CREATE INDEX'):
                    print(f"Created {query.split()[2]}", flush=True)
            print('Checking the completed snapshot...', flush=True)
            checks = verify(con)
            counts = con.execute('SELECT * FROM restricted.quality_counts ORDER BY source, issue').fetchall()
            summary = {
                'as_of_date': as_of.isoformat(), 'duckdb_version': duckdb.__version__,
                'duration_seconds': round(time.monotonic() - started, 2),
                'sources': inventory,
                'quality_counts': [dict(zip(('source', 'issue', 'affected_records'), row)) for row in counts],
                'identity_counts': [dict(zip(('source_system', 'status', 'source_keys'), row)) for row in
                                    con.execute('SELECT source_system, status, count(*) FROM restricted.identity_map GROUP BY ALL ORDER BY ALL').fetchall()],
                'golden_customers': con.execute('SELECT count(*) FROM golden.c360').fetchone()[0],
                'checks': checks,
            }
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
    (report_dir / 'quality_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    lines = ['# Data quality report', '', f'Snapshot: {as_of}. Full-file scans of the priority tables.', '',
             '| Source | Check | Affected records |', '| --- | --- | ---: |']
    lines += [f'| {source} | {issue} | {count:,} |' for source, issue, count in counts]
    lines += ['', '## Identity coverage', '', '| Source | State | Source keys |', '| --- | --- | ---: |']
    lines += [f"| {r['source_system']} | {r['status']} | {r['source_keys']:,} |" for r in summary['identity_counts']]
    lines += ['', f"Golden customer rows: {summary['golden_customers']:,}.", '',
              'Confidence categories describe matching evidence, not calibrated probabilities. Keys without sufficient complete identity evidence, '
              'inconsistent profiles, multiple candidates and unvalidated CRM duplicate pointers are quarantined.', '',
              'Duplicate source rows are removed before joins. Conflicting payloads for a current entity key are '
              'quarantined, never chosen arbitrarily. Invalid money, DPD and required dates are quarantined.', '',
              'Contacts reconcile channel/channel_v2; disagreements remain quarantined. '
              'Unlinked cases and interactions are retained in restricted tables for review.', '',
              'The approved C360 excludes names, DOB, phones and protected attributes. Deposit balances are separate '
              'from credit/loan debt. Unknown totals remain null and have coverage counts.', '',
              'This report covers the current snapshot foundation, not a historical feature store. '
              'Feature parity, authentication, natural-language answering and model evaluation are documented '
              'separately in the application and model reports. '
              'CSV tables outside the priority set and Parquet histories have raw views but have not undergone row-level quality checks.', '',
              '## Verification', '']
    lines += [f'- {check}' for check in checks]
    (report_dir / 'data_quality.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('golden_customers', 'duration_seconds', 'identity_counts')}, indent=2), flush=True)
    return summary


def verify(con):
    queries = {
        'All five source systems have accepted identity links': "SELECT count(*) FROM (VALUES ('crm'),('cards'),('lending'),('core_banking'),('collections')) s(system) WHERE NOT EXISTS(SELECT 1 FROM restricted.identity_map m WHERE m.source_system=s.system AND m.status='accepted')",
        'All three product sources have served account records': "SELECT count(*) FROM (VALUES ('cards'),('lending'),('core_banking')) s(system) WHERE NOT EXISTS(SELECT 1 FROM curated.accounts a WHERE a.source_system=s.system)",
        'Golden customer keys are unique': 'SELECT count(*) - count(DISTINCT golden_customer_id) FROM golden.c360',
        'Source identity keys are unique': "SELECT count(*) FROM (SELECT source_system, source_key FROM restricted.identity_map GROUP BY ALL HAVING count(*)>1)",
        'Every accepted link resolves to a golden customer': "SELECT count(*) FROM restricted.identity_map m LEFT JOIN golden.c360 g USING(golden_customer_id) WHERE m.status='accepted' AND g.golden_customer_id IS NULL",
        'Quarantined identity links have no golden ID': "SELECT count(*) FROM restricted.identity_map WHERE status<>'accepted' AND golden_customer_id IS NOT NULL",
        'Account keys are unique': 'SELECT count(*) FROM (SELECT source_system, account_id FROM curated.accounts GROUP BY ALL HAVING count(*)>1)',
        'Case keys are unique': 'SELECT count(*)-count(DISTINCT case_id) FROM curated.cases',
        'All served case/account links agree on customer identity': "WITH case_links AS MATERIALIZED (SELECT l.source_system,l.account_id,c.golden_customer_id FROM curated.case_accounts l JOIN curated.cases c USING(case_id)) SELECT count(*) FROM case_links l JOIN curated.accounts a USING(source_system,account_id) WHERE l.golden_customer_id<>a.golden_customer_id",
        'Served interactions have no contradictory resolved account owner': "SELECT count(*) FROM (SELECT account_id,golden_customer_id FROM curated.contacts UNION ALL SELECT account_id,golden_customer_id FROM curated.promises UNION ALL SELECT account_id,golden_customer_id FROM curated.notes) i WHERE contradicts_account_owner(i.account_id,i.golden_customer_id)",
        'Served transcripts agree with case and resolved contact provenance': "SELECT count(*) FROM curated.transcripts t LEFT JOIN curated.cases c USING(case_id) LEFT JOIN restricted.contact_records x USING(contact_id) WHERE c.golden_customer_id IS DISTINCT FROM t.golden_customer_id OR (x.contact_id IS NOT NULL AND (x.quality_reason IS NOT NULL OR x.case_id IS DISTINCT FROM t.case_id OR x.golden_customer_id IS DISTINCT FROM t.golden_customer_id)) OR (t.contact_link_state='validated' AND x.contact_id IS NULL)",
        'C360 credit/loan totals match separately aggregated accounts': "SELECT count(*) FROM (SELECT golden_customer_id,sum(balance_cad) total FROM curated.accounts WHERE source_system IN ('cards','lending') GROUP BY 1) a JOIN golden.c360 g USING(golden_customer_id) WHERE a.total IS DISTINCT FROM g.credit_loan_outstanding_cad",
    }
    for label, query in queries.items():
        print(f'Checking: {label}', flush=True)
        violations = con.execute(query).fetchone()[0]
        if violations:
            raise RuntimeError(f'{label}: {violations} violations')
    protected = {'first_name', 'last_name', 'date_of_birth', 'primary_phone_raw', 'age', 'age_band',
                 'gender_code', 'marital_status', 'citizenship_status', 'household_size', 'newcomer_program_flag',
                 'accessibility_needs_flag', 'vulnerability_flag', 'vulnerable_customer_flag', 'postal_code', 'fsa'}
    columns = {row[0] for row in con.execute('DESCRIBE golden.c360').fetchall()}
    if protected & columns:
        raise RuntimeError('Matching-only or protected fields leaked into C360')
    expected = set(json.loads((ROOT / 'contracts' / 'c360.json').read_text(encoding='utf-8'))['schema'])
    if columns != expected:
        raise RuntimeError(f'C360 schema differs from its contract: {columns ^ expected}')
    return list(queries) + ['C360 matches its contract and excludes matching-only/protected fields']


def inspect_case(database, case_id):
    with duckdb.connect(str(database), read_only=True) as con:
        rows = con.execute('SELECT * FROM curated.cases WHERE case_id=?', [case_id])
        case = rows.fetchone()
        if not case:
            raise ValueError('Case is absent or quarantined; inspect restricted.case_records locally')
        result = {'case': dict(zip([c[0] for c in rows.description], case))}
        for name, query in {
            'customer': 'SELECT g.* FROM golden.c360 g JOIN curated.cases c USING(golden_customer_id) WHERE c.case_id=?',
            'accounts': 'SELECT a.* FROM curated.case_accounts l JOIN curated.accounts a USING(source_system,account_id) WHERE l.case_id=?',
            'recent_contacts': 'SELECT * FROM curated.contacts WHERE case_id=? ORDER BY contact_ts_utc DESC LIMIT 5',
            'promises': 'SELECT * FROM curated.promises WHERE case_id=? ORDER BY ptp_due_date DESC LIMIT 5',
            'note_sources': 'SELECT note_id,note_ts_utc,source_file FROM curated.notes WHERE case_id=? ORDER BY note_ts_utc DESC LIMIT 5',
        }.items():
            rows = con.execute(query, [case_id])
            result[name] = [dict(zip([c[0] for c in rows.description], row)) for row in rows.fetchall()]
        print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'case'))
    parser.add_argument('--release', type=Path, default=DEFAULT_RELEASE)
    parser.add_argument('--database', type=Path, default=ROOT / 'data' / 'collections.duckdb')
    parser.add_argument('--reports', type=Path, default=ROOT / 'reports')
    parser.add_argument('--as-of', type=date.fromisoformat, default=date(2026, 9, 28))
    parser.add_argument('--case-id')
    args = parser.parse_args()
    if args.command == 'build':
        build(args.release, args.database, args.reports, args.as_of)
    elif not args.case_id:
        parser.error('--case-id is required for the case command')
    else:
        inspect_case(args.database, args.case_id)
