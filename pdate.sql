-- Jalali <-> Gregorian SQL UDFs.
-- Public supported Gregorian range: 1900-01-01 .. 2123-12-31.
-- The retained 33-year algorithm is not an all-centuries astronomical calendar.
-- pdate preserves the input timestamp's timezone; convert timezone explicitly
-- before calling it when a particular business timezone is required.
-- gdate returns Date32 (not Date) to preserve dates before 1970.

-- Zero-based month helpers retained for backwards compatibility.
-- February/Esfand are common-year lengths; leap adjustment is year-dependent.
CREATE OR REPLACE FUNCTION pdate_gdm AS (i) ->
    arrayElement([31,28,31,30,31,30,31,31,30,31,30,31], toInt64(i) + 1);

CREATE OR REPLACE FUNCTION pdate_jdm AS (i) ->
    arrayElement([31,31,31,31,31,31,30,30,30,30,30,29], toInt64(i) + 1);

-- Native Gregorian day arithmetic handles month lengths and century leap years.
-- 135140 is the exact distance from 1600-01-01 to 1970-01-01. Using a Date32
-- epoch avoids constructing the unrepresentable ClickHouse date 1600-01-01.
CREATE OR REPLACE FUNCTION pdate_gdn AS (gregorian_date) ->
    dateDiff('day', toDate32('1970-01-01'), toDate32(gregorian_date)) + 135140;

-- These two helpers take the Jalali day number: pdate_gdn(date) - 79.
CREATE OR REPLACE FUNCTION pdate_jy AS (jdn) ->
    979 + 33 * intDiv(jdn, 12053)
        + 4 * intDiv(jdn % 12053, 1461)
        + if((jdn % 12053) % 1461 >= 366,
             intDiv(((jdn % 12053) % 1461) - 1, 365), 0);

CREATE OR REPLACE FUNCTION pdate_j3 AS (jdn) ->
    if((jdn % 12053) % 1461 >= 366,
       (((jdn % 12053) % 1461) - 1) % 365,
       (jdn % 12053) % 1461);

-- Six 31-day months, then five 30-day months. Esfand starts at index 336,
-- NOT 335. Day index 365 is Esfand 30 in a leap year.
CREATE OR REPLACE FUNCTION pdate_jm AS (day_of_year) ->
    if(day_of_year < 186, intDiv(day_of_year, 31) + 1,
       intDiv(toInt64(day_of_year) - 186, 30) + 7);

CREATE OR REPLACE FUNCTION pdate_jd AS (day_of_year) ->
    if(day_of_year < 186, day_of_year % 31 + 1,
       (toInt64(day_of_year) - 186) % 30 + 1);

-- Singleton lambdas bind intermediate results once. This avoids expanding the
-- entire Gregorian conversion repeatedly when ClickHouse inlines SQL UDFs.
-- Keep the range check numeric. On ClickHouse 25.8, the preimage optimizer
-- rewrites bare toYear(DateTime) bounds to timestamps outside DateTime's range,
-- incorrectly rejecting valid column values (constant-only tests miss this).
CREATE OR REPLACE FUNCTION pdate AS (gregorian_date) ->
    arrayMap(jdn ->
        arrayMap(day_of_year -> concat(
            toString(pdate_jy(jdn)), '-',
            leftPad(toString(pdate_jm(day_of_year)), 2, '0'), '-',
            leftPad(toString(pdate_jd(day_of_year)), 2, '0')
        ), [pdate_j3(jdn)])[1],
        [pdate_gdn(gregorian_date) - 79 + throwIf(
            toInt64(toYear(gregorian_date)) < 1900 OR toInt64(toYear(gregorian_date)) > 2123,
            'pdate supports Gregorian dates from 1900-01-01 through 2123-12-31')]
    )[1];

CREATE OR REPLACE FUNCTION pdate_jdn AS (jy, jm, jd) ->
    12053 * intDiv(toInt64(jy) - 979, 33)
    + 1461 * intDiv((toInt64(jy) - 979) % 33, 4)
    + ((toInt64(jy) - 979) % 33 % 4) * 365
    + if((toInt64(jy) - 979) % 33 % 4 > 0, 1, 0)
    + if(jm <= 7, (toInt64(jm) - 1) * 31, 186 + (toInt64(jm) - 7) * 30)
    + (toInt64(jd) - 1);

-- Reject invalid inputs before returning a normalized/overflowed date.
CREATE OR REPLACE FUNCTION pdate_gdate_checked AS (jy, jm, jd) ->
    arrayMap(day_offset -> addDays(toDate32('1970-01-01'),
        day_offset + throwIf(
            jy < 1278 OR jy > 1502 OR jm < 1 OR jm > 12 OR jd < 1
            OR jd > if(jm <= 6, 31, if(jm <= 11, 30,
                pdate_jdn(jy + 1, 1, 1) - pdate_jdn(jy, 1, 1) - 336))
            OR day_offset < dateDiff('day', toDate32('1970-01-01'), toDate32('1900-01-01'))
            OR day_offset > dateDiff('day', toDate32('1970-01-01'), toDate32('2123-12-31')),
            'Invalid Jalali date or result outside Gregorian 1900-01-01 through 2123-12-31')
    ), [pdate_jdn(jy, jm, jd) + 79 - 135140])[1];

CREATE OR REPLACE FUNCTION gdate AS (jalali_date) ->
    arrayMap(parts -> pdate_gdate_checked(
        toInt64OrZero(parts[1]), toInt64OrZero(parts[2]),
        toInt64OrZero(parts[3]) + throwIf(
            NOT match(ifNull(jalali_date, ''), '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'),
            'gdate requires a non-null Jalali date in ASCII YYYY-MM-DD format')
    ), [splitByChar('-', ifNull(jalali_date, ''))])[1];
