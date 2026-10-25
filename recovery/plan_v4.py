"""Reconstruction plan v4.

Certain clusters = telemetry anchors + runs between two anchors of the same file
whose disk distance equals their file distance. Everything else is filled per
gap from clusters not certainly owned by another file; when more candidates
than slots exist, the gap is filled greedily, judged by decoding.

usage: plan_v4.py IMG pairs.json metaindex.bin names.json OUT_PREFIX [workers]
"""
import sys, os, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool
import chain, greedy
from chain import CL, HEAP, disk_cluster
from card import HEADER_OVERRIDES

IMG, PAIRS, INDEX, NAMES, OUT = sys.argv[1:6]
WORKERS = int(sys.argv[6]) if len(sys.argv) > 6 else 4


def load(mv, names):
    f = open(IMG, 'rb')
    f.seek(mv['moov'])
    sz = int.from_bytes(f.read(4), 'big')
    f.seek(mv['moov'])
    moov = f.read(sz)
    base = HEADER_OVERRIDES.get(mv['moov'], mv['ftyp'])
    bo = (base - HEAP) % CL if base is not None else 0
    meta = dict(created=mv['created'], moov=mv['moov'], moov_size=sz, base=base, name=names.get(str(mv['moov'])))
    return f, moov, bo, meta


def anchors_for(args):
    mv, names = args
    idx = chain.load_index(INDEX) if not hasattr(anchors_for, 'idx') else anchors_for.idx
    anchors_for.idx = idx
    f, moov, bo, meta = load(mv, names)
    fm = chain.FileModel(moov, bo)
    chain.phase_a(fm, idx, known_base=meta['base'])
    if (mv['moov'] - HEAP) % CL == (fm.mdat_end + bo) % CL:
        fm.anchor.setdefault(fm.fc(fm.mdat_end), set()).add(disk_cluster(mv['moov']))
    return meta, chain.anchors_clean(fm)


def certain_set(anchors):
    ks = sorted(anchors)
    cert = {k: anchors[k] for k in ks}
    for ka, kb in zip(ks, ks[1:]):
        if anchors[kb] - anchors[ka] == kb - ka:
            for j in range(1, kb - ka):
                cert[ka + j] = anchors[ka] + j
    return cert


def solve(args):
    mv, names, anchors, taken = args
    f, moov, bo, meta = load(mv, names)
    fm = chain.FileModel(moov, bo)
    dec = greedy.Decoder(moov)
    cert = certain_set(anchors)
    for k, d in cert.items():
        fm.clusters[k] = d
    ks = sorted(anchors)
    gaps = []
    for ka, kb in zip(ks, ks[1:]):
        n = kb - ka - 1
        if n == 0 or all(fm.clusters[ka + j] is not None for j in range(1, n + 1)):
            continue
        da, db = anchors[ka], anchors[kb]
        free = [c for c in range(da + 1, db) if c not in taken] if db > da else []
        gaps.append((ka, kb, n, free))
        for j in range(n):          # provisional allocation-order fill
            fm.clusters[ka + 1 + j] = free[j] if j < len(free) else None
    if ks:
        for k in range(ks[-1] + 1, fm.nfc):
            fm.clusters[k] = anchors[ks[-1]] + (k - ks[-1])
    report = []
    for ka, kb, n, free in gaps:
        if len(free) == n:
            report.append((ka, kb, n, len(free), 'exact'))
            continue
        if len(free) < n or n > 40:
            for j in range(n):
                fm.clusters[ka + 1 + j] = None
            report.append((ka, kb, n, len(free), 'short' if len(free) < n else 'too-large'))
            continue
        how, _ = greedy.fill_gap(dec, fm, f, ka, kb, n, free, CL)
        report.append((ka, kb, n, len(free), how))
    bad = chain.verify(fm, f)
    # garbage check on every frame touching a gap
    starts = [o for o, _ in fm.video]
    touched = set()
    for ka, kb, n, free in gaps:
        lo, hi = (ka + 1) * CL - bo, kb * CL - bo
        touched.update(i for i, (o, s) in enumerate(fm.video) if o < hi and o + s > lo)
    garbage = {}
    for i in sorted(touched):
        g, t = greedy.score(dec, fm, f, i, i)
        if g > 0:
            garbage[i] = g
    lost = sum(1 for c in fm.clusters if c is None)
    print(meta['name'], 'gaps', len(gaps), 'nal-bad', len(bad), 'garbage-frames', len(garbage), 'lost', lost, flush=True)
    return meta, bo, fm.mdat_end, list(fm.clusters), dict(gaps=report, nal_bad=bad, garbage=garbage, lost=lost)


if __name__ == '__main__':
    P = json.load(open(PAIRS))
    names = json.load(open(NAMES))
    mvs = P['pairs']
    with Pool(WORKERS) as p:
        A = p.map(anchors_for, [(mv, names) for mv in mvs])
    owner = {}
    for i, (meta, anc) in enumerate(A):
        for k, d in certain_set(anc).items():
            owner.setdefault(d, set()).add(i)
    clash = {d: s for d, s in owner.items() if len(s) > 1}
    print('certain clusters', len(owner), 'clashes', len(clash), flush=True)
    jobs = []
    for i, mv in enumerate(mvs):
        taken = {d for d, s in owner.items() if s - {i}}
        jobs.append((mv, names, A[i][1], taken))
    order = sorted(range(len(jobs)), key=lambda i: len(A[i][1]))
    with Pool(WORKERS) as p:
        res = p.map(solve, [jobs[i] for i in order], chunksize=1)
    pickle.dump([(m, bo, e, c) for m, bo, e, c, _ in res], open(OUT + '.chains.pkl', 'wb'))
    json.dump([dict(m, **r, frames=None) for m, bo, e, c, r in res], open(OUT + '.json', 'w'), indent=1, default=str)
