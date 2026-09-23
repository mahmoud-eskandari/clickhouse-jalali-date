# Converter regression results

Recorded run: 2026-09-23. The complete suite passed against both query-local SQL
and installed UDFs on ClickHouse 25.8.29.51. Both test modes are read-only.
Earlier constant-value tests missed the non-constant DateTime optimizer path;
the suite now explicitly covers that regression.

| Check | Result |
|---|---|
| ClickHouse engine | 25.8.29.51 |
| Independent reference | Node 23.11.0, ICU 77.1, `Intl` Persian calendar, UTC |
| Exhaustive range | 1900-01-01 through 2123-12-31 inclusive |
| Gregorian → Jalali compared with ICU | 81,814 / 81,814 passed |
| Gregorian → Jalali → Gregorian | 81,814 / 81,814 passed |
| Invalid-input rejection | 48 / 48 passed (24 inputs × two short-circuit modes) |
| Input types/timezone/nullable/pre-1970 probes | 5 / 5 passed |
| Non-constant column/optimizer regressions | 106 / 106 passed in each test mode |
| Nested calendar aggregation/query-tree regression | Passed, 13 month groups |
| Installed-function fingerprint before/after | Unchanged |
| Writes performed by test suites | 0 |

Tested `pdate.sql` SHA-256:
`063c83548299fc68e04bdf2ccfcaa8f071bfa5f7ef1e9f4b82627ea385af92d4`

By default the test executes the actual SQL expressions as uniquely named
query-local `WITH` lambdas under `readonly=1`; `--installed` tests the installed
UDFs instead. Neither mode executes `CREATE FUNCTION`. Installed function
definitions are fingerprinted before and after each suite to check that they
remain unchanged. `gdate` returns **Date32**, an intentional public return-type
change from the original implementation (not changed by the optimizer fix).

The new column suite was first run against the uncorrected local SQL and failed
with an unexpected range error for valid DateTime column values. The fix keeps `toYear` comparisons
numeric via `toInt64`, preventing an unsafe DateTime preimage rewrite. Coverage
includes optimizer=1 and optimizer=0, all four input types, nullable columns,
UTC/Asia/Tehran, Nowruz, out-of-range rejection and monthly WHERE/GROUP BY.

Independent exploration of the retained 33-year algorithm through 2199 found its
first divergence from this ICU reference on 2124-03-20. Public functions therefore
reject dates after 2123-12-31 instead of claiming all-centuries accuracy. This is
an implementation/reference validation, not an astronomical-calendar proof.

ClickHouse's `toDate32('1899-12-31')` already clamps to `1900-01-01` before any UDF
receives it. A downstream function cannot recover the discarded original string;
callers must validate raw inputs before a lossy ClickHouse cast. The inverse
`gdate` validates its original string and rejects out-of-range results.
