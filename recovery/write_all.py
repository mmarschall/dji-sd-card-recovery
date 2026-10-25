"""Write every planned video. usage: write_all.py IMG plan.json.chains.pkl OUTDIR [name ...]"""
import sys, os, pickle, struct, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain import CL, HEAP, cluster_abs

IMG, CHAINS, OUTDIR = sys.argv[1:4]
only = set(sys.argv[4:])
f = open(IMG, 'rb')
PLANS = pickle.load(open(CHAINS, 'rb'))
# standard DJI header (ftyp + free + free = 504 bytes), taken from the first file whose own header is intact
TEMPLATE = None
for meta, base_off, _, chain in PLANS:
    if meta['base'] is not None and base_off == 0 and chain and chain[0] is not None:
        f.seek(meta['base'])
        TEMPLATE = f.read(504)
        break
if TEMPLATE is None or TEMPLATE[4:8] != b'ftyp':
    sys.exit('no intact header found to use as template')

os.makedirs(OUTDIR, exist_ok=True)
for meta, base_off, mdat_end, chain in PLANS:
    name = meta['name']
    if only and name not in only:
        continue
    out = os.path.join(OUTDIR, name)
    tmp = out + '.part'
    f.seek(meta['moov'])
    moov = f.read(meta['moov_size'])
    with open(tmp, 'wb') as o:
        pos = base_off
        end = mdat_end + base_off
        while pos < end:
            k = pos // CL
            take = min(CL - pos % CL, end - pos)
            d = chain[k] if k < len(chain) else None
            if d is None:
                o.write(b'\0' * take)
            else:
                f.seek(cluster_abs(d) + pos % CL)
                o.write(f.read(take))
            pos += take
        header_ok = chain[0] is not None and base_off == 0 and meta['base'] is not None
        o.seek(0)
        if not header_ok:
            o.write(TEMPLATE)
        o.seek(504)
        o.write(struct.pack('>I4s', mdat_end - 504, b'mdat'))
        o.seek(mdat_end)
        o.write(moov)
    os.replace(tmp, out)
    t = datetime.datetime.fromisoformat(meta['created']).replace(tzinfo=datetime.timezone.utc).timestamp()
    os.utime(out, (t, t))
    print('wrote', name, os.path.getsize(out), flush=True)
