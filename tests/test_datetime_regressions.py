"""Column/optimizer regressions, shared by local-SQL and installed-UDF tests."""
from collections import Counter
from datetime import date, timedelta


def run_column_regressions(query, reference):
    checks = 0
    constructors = {
        'Date': "toDate('{day}')",
        'Date32': "toDate32('{day}')",
        'DateTime': "toDateTime('{day} 12:00:00','{zone}')",
        'DateTime64': "toDateTime64('{day} 12:00:00.123456',6,'{zone}')",
    }
    for optimize in (1, 0):
        settings = {'optimize_time_filter_with_preimage': optimize}
        for kind, constructor in constructors.items():
            for zone in ('UTC', 'Asia/Tehran'):
                for first in ('2025-03-20', '2026-03-20', '2025-10-04'):
                    expression = 'addDays(' + constructor.format(day=first, zone=zone) + ',toInt32(number))'
                    expected = [reference[(date.fromisoformat(first) + timedelta(days=i)).isoformat()]
                                for i in range(3)]
                    for nullable in (False, True):
                        column = f'if(number=1,NULL,{expression})' if nullable else expression
                        rows = query(f'SELECT pdate(d) FROM (SELECT number,{column} d FROM numbers(3)) ORDER BY number', **settings)
                        assert rows == [(None if nullable and i == 1 else j,) for i, j in enumerate(expected)], (kind, zone, first, nullable, optimize, rows)
                        checks += 1

        # DateTime columns in WHERE + GROUP BY: the shape of the failed report.
        rows = query("""SELECT substring(pdate(d),1,7) period,count(),min(pdate(d)),max(pdate(d))
            FROM (SELECT addDays(toDateTime('2025-09-22 12:00:00','Asia/Tehran'),toInt32(number)) d FROM numbers(368))
            WHERE pdate(d)>='1404-07-01' AND pdate(d)<='1405-07-01'
            GROUP BY period ORDER BY period""", **settings)
        selected = sorted(j for g, j in reference.items() if '2025-09-23' <= g <= '2026-09-23')
        counts = Counter(j[:7] for j in selected)
        expected = [(month, count, min(j for j in selected if j[:7] == month),
                     max(j for j in selected if j[:7] == month)) for month, count in sorted(counts.items())]
        assert rows == expected, (optimize, rows, expected)
        checks += 1

        # The numeric guard must still reject unsupported dates, not be removed.
        for kind in ('Date', 'Date32', 'DateTime64'):
            expression = constructors[kind].format(day='2124-01-01', zone='UTC')
            try:
                query(f'SELECT pdate(addDays({expression},toInt32(number))) FROM numbers(2)', **settings)
            except Exception as exc:
                assert 'pdate supports Gregorian dates' in str(exc), str(exc)
            else:
                raise AssertionError(f'Unsupported {kind} column accepted with optimizer={optimize}')
            checks += 1

        # Preserve the timestamp timezone at the Nowruz midnight boundary.
        rows = query("""SELECT pdate(d),pdate(toTimeZone(d,'Asia/Tehran'))
            FROM (SELECT addSeconds(toDateTime('2026-03-20 21:00:00','UTC'),toInt32(number)) d FROM numbers(2))""", **settings)
        assert rows == [('1404-12-29', '1405-01-01')] * 2, rows
        checks += 1
    return checks
