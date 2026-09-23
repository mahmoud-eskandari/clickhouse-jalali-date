"""Test the ACTUAL SQL in a read-only ClickHouse query, without installing it.

CREATE definitions become uniquely named WITH lambdas. Nothing issues DDL,
inserts, updates, or queries application tables. Node/ICU is the independent
calendar oracle. Invoke run(client) or use CLICKHOUSE_* environment variables.
"""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_datetime_regressions import run_column_regressions

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'jalali_file_test_'


def local_functions():
    source = re.sub(r'--[^\n]*', '', (ROOT / 'pdate.sql').read_text())
    functions = []
    for statement in source.split(';'):
        if not statement.strip():
            continue
        match = re.fullmatch(r'\s*CREATE OR REPLACE FUNCTION (\w+) AS\s+(.+)\s*', statement, re.S)
        if not match:
            raise AssertionError('Unexpected SQL statement: tests only accept function definitions')
        functions.append(match.groups())
    assert len(functions) == len({name for name, _ in functions})
    names = [name for name, _ in functions]
    calls = re.compile(r'\b(' + '|'.join(sorted(names, key=len, reverse=True)) + r')(?=\s*\()')
    def rename(expression):
        return calls.sub(lambda m: PREFIX + m[0], expression)
    definitions = ',\n'.join(rename(body) + ' AS ' + PREFIX + name for name, body in functions)
    return 'WITH ' + definitions + '\n', rename, names


def run(client, *, installed=False):
    definitions, rename, names = local_functions()
    if installed:
        definitions, rename = '', lambda sql: sql
    def query(sql, **extra):
        assert sql.lstrip().upper().startswith('SELECT ')
        return client.query(definitions + rename(sql), settings={
            'readonly': 1, 'max_execution_time': 30, **extra}).result_rows
    def fingerprint():
        records = client.query('SELECT name,create_query FROM system.functions WHERE name IN {names:Array(String)} ORDER BY name',
            parameters={'names': names}, settings={'readonly': 1, 'max_execution_time': 10}).result_rows
        return hashlib.sha256(json.dumps(records).encode()).hexdigest()
    before = fingerprint()
    version = client.query('SELECT version()', settings={'readonly': 1}).first_row[0]
    oracle = json.loads(subprocess.check_output(['node', str(ROOT / 'tests/persian_oracle.mjs')], text=True))
    reference = dict(oracle['rows'])
    days = len(reference)
    print(json.dumps({'phase':'oracle_ready', 'days':days, 'node':oracle['node'], 'icu':oracle['icu'], 'clickhouse':version}), flush=True)

    column_checks = run_column_regressions(query, reference)
    print(json.dumps({'phase':'column_regressions_passed','checks':column_checks}), flush=True)

    gm,jm = query('SELECT arrayMap(i -> pdate_gdm(i),range(12)),arrayMap(i -> pdate_jdm(i),range(12))')[0]
    assert gm == [31,28,31,30,31,30,31,31,30,31,30,31], gm
    assert jm == [31]*6 + [30]*5 + [29], jm
    for offset in range(0,days,10000):
        count = min(10000,days-offset)
        rows = query(f'''SELECT toString(d),pdate(d) AS j,toString(gdate(j)),toTypeName(gdate(j))
            FROM (SELECT addDays(toDate32('1900-01-01'),toInt32(number)+{offset}) AS d FROM numbers({count}))
            ORDER BY d''')
        assert len(rows) == count
        for gregorian,jalali,back,kind in rows:
            assert jalali == reference[gregorian], (gregorian,jalali,reference[gregorian])
            assert back == gregorian, (gregorian,jalali,back)
            assert kind == 'Date32', kind
    print(json.dumps({'phase':'exhaustive_passed','days':days,'forward_icu_matches':days,'round_trips':days}), flush=True)

    # Input types, leap boundaries, non-constant columns and explicit timezone.
    probes = [
        ("SELECT pdate(toDate('2025-10-04')),pdate(toDateTime('2025-10-04 23:59:59','Asia/Tehran')),pdate(toDateTime64('2025-10-04 23:59:59.123456',6,'Asia/Tehran'))", [('1404-07-12',)*3]),
        ("SELECT pdate(toDate('2026-03-20')),toString(gdate('1404-12-29')),pdate(toDate('2025-03-20')),toString(gdate('1403-12-30'))", [('1404-12-29','2026-03-20','1403-12-30','2025-03-20')]),
        ("SELECT pdate(toDateTime('2026-03-20 21:00:00','UTC')),pdate(toTimeZone(toDateTime('2026-03-20 21:00:00','UTC'),'Asia/Tehran'))", [('1404-12-29','1405-01-01')]),
        ("SELECT pdate(CAST(NULL,'Nullable(Date32)'))", [(None,)]),
        ("SELECT toString(gdate('1348-10-10'))", [('1969-12-31',)]),
    ]
    for sql,expected in probes:
        assert query(sql) == expected, sql

    invalid = [None,'','1405-1-01','1405-01-1',' 1405-01-01','1405-01-01 ',
        '۱۴۰۵-۰۱-۰۱','1405/01/01','abcd-01-01','1405-01-01x','1405-01-01\n',
        '1405-00-01','1405-13-01','1405-01-00','1405-01-32','1405-07-31',
        '1404-11-31','1404-12-30','1403-12-31','0000-01-01','9999-01-01',
        '1278-10-10','1502-10-11','1503-01-01']
    rejected = 0
    for value in invalid:
        literal = 'NULL' if value is None else "'" + value.replace('\\','\\\\').replace("'","\\'").replace('\n','\\n') + "'"
        for mode in ('enable','disable'):
            try:
                query('SELECT gdate('+literal+')', short_circuit_function_evaluation=mode)
            except Exception as exc:
                assert ('gdate requires' in str(exc) or 'Invalid Jalali date' in str(exc)), str(exc)
                rejected += 1
            else:
                raise AssertionError('Invalid input accepted: '+repr(value))
    # ClickHouse itself clamps an out-of-domain Date32 literal to 1900-01-01
    # before pdate runs; no downstream UDF can recover that original literal.
    assert query("SELECT toString(toDate32('1899-12-31'))") == [('1900-01-01',)]
    for d in ('2124-01-01',):
        try:
            query(f"SELECT pdate(toDate32('{d}'))")
        except Exception as exc:
            assert 'pdate supports' in str(exc), str(exc)
        else:
            raise AssertionError('Unsupported range accepted: '+d)

    # Calendar+measurement shape that previously exceeded the UDF query-tree cap.
    regression = query('''SELECT substring(pdate(d),1,7) period,min(pdate(d)),max(pdate(d)),
        pdate(subtractDays(min(d),1)),pdate(addDays(max(d),1))
        FROM (SELECT addDays(gdate('1404-06-31'),toInt32(number)) d FROM numbers(366))
        GROUP BY period ORDER BY period''')
    assert len(regression) == 13
    assert fingerprint() == before, 'Installed server functions changed during read-only tests'
    summary = {'status':'passed','days':days,'forward_icu_matches':days,'round_trips':days,
        'invalid_input_checks':rejected,'type_timezone_probes':len(probes),
        'column_optimizer_regressions':column_checks,'installed_functions_tested':installed,
        'query_tree_regression':'passed','database_writes':0,
        'sql_sha256':hashlib.sha256((ROOT/'pdate.sql').read_bytes()).hexdigest(),
        'clickhouse':version,'node':oracle['node'],'icu':oracle['icu']}
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == '__main__':
    import argparse
    import clickhouse_connect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', action='store_true',
        help='Test already-installed UDFs instead of query-local SQL; still read-only')
    args = parser.parse_args()
    if not os.environ.get('CLICKHOUSE_HOST'):
        raise SystemExit('Set CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER and CLICKHOUSE_PASSWORD for a read-only test connection')
    client = clickhouse_connect.get_client(host=os.environ['CLICKHOUSE_HOST'],
        port=int(os.environ.get('CLICKHOUSE_PORT','8123')),
        username=os.environ.get('CLICKHOUSE_USER','default'),password=os.environ.get('CLICKHOUSE_PASSWORD',''),
        secure=os.environ.get('CLICKHOUSE_SECURE','0')=='1',settings={'readonly':1},
        connect_timeout=5,send_receive_timeout=40)
    try:run(client, installed=args.installed)
    finally:client.close()
