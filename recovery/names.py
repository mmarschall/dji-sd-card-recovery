"""Give each recovered video its original DJI file name.

The camera's media database (SQLite fragments on the card) lists names like
DJI_YYYYMMDDhhmmss_NNNN_D.MP4 with the local start time. The moov's mvhd
creation time is UTC; converting it to the camera's time zone and matching it to
those names recovers the original name and running number.

usage: names.py scan2.txt pairs.json names.json [TIMEZONE]
TIMEZONE is an IANA name such as America/New_York; default UTC.
"""
import sys, re, json, datetime, collections
from zoneinfo import ZoneInfo

SCAN, PAIRS, OUT = sys.argv[1:4]
TZ = ZoneInfo(sys.argv[4] if len(sys.argv) > 4 else 'UTC')
names = {}
for line in open(SCAN):
    m = re.search(r"(DJI_(\d{14})_(\d{4})_D\.MP4)", line)
    if m:
        names[m.group(2)] = m.group(1)

out = {}
for mv in json.load(open(PAIRS))['pairs']:
    utc = datetime.datetime.fromisoformat(mv['created']).replace(tzinfo=datetime.timezone.utc)
    loc = utc.astimezone(TZ)
    hit = None
    for d in (0, -1, 1, -2, 2, -3, 3):
        k = (loc + datetime.timedelta(seconds=d)).strftime('%Y%m%d%H%M%S')
        if k in names:
            hit = names[k]
            break
    out[str(mv['moov'])] = hit or 'DJI_%s_0000_D.MP4' % loc.strftime('%Y%m%d%H%M%S')

dups = [k for k, v in collections.Counter(out.values()).items() if v > 1]
if dups:
    sys.exit('duplicate names: %s' % dups)
json.dump(out, open(OUT, 'w'), indent=1)
print(len(out), 'names,', sum(1 for v in out.values() if not v.endswith('_0000_D.MP4')), 'matched to the camera database')
