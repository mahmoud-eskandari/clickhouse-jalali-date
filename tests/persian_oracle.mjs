// Independent reference: Node's ICU/Intl Persian calendar, not our SQL algorithm.
const [start = '1900-01-01', end = '2123-12-31'] = process.argv.slice(2);
const first = Date.parse(`${start}T12:00:00Z`);
const last = Date.parse(`${end}T12:00:00Z`);
if (!Number.isFinite(first) || !Number.isFinite(last) || last < first || (last-first)/86400000 > 100000)
  throw new Error('Invalid/beyond-test-budget date range');
const formatter = new Intl.DateTimeFormat('en-CA-u-ca-persian', {
  timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
});
if (formatter.resolvedOptions().calendar !== 'persian') throw new Error('Persian ICU calendar unavailable');
const rows = [];
for (let ms = first; ms <= last; ms += 86400000) {
  const d = new Date(ms);
  const p = Object.fromEntries(formatter.formatToParts(d).map(x => [x.type, x.value]));
  rows.push([d.toISOString().slice(0,10), `${p.year.padStart(4,'0')}-${p.month}-${p.day}`]);
}
process.stdout.write(JSON.stringify({node:process.versions.node, icu:process.versions.icu, rows}));
