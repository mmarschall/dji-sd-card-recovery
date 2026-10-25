"""Recover clips whose header cluster is gone: anchor telemetry backwards from the moov.

The moov position is certain. Walking the djmd/dbgi samples from the last to the
first, each candidate must continue the timestamp (one frame ~ 16683 us earlier)
and the frame counter of the previous accepted anchor.

usage: lost3.py IMG pairs.json metaindex.bin names.json plan_v4 OUT_PREFIX
"""
import sys, os, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain, greedy
from chain import CL, HEAP, disk_cluster

IMG, PAIRS, INDEX, NAMES, PLAN, OUT = sys.argv[1:7]
DT = 1001 / 60000 * 1e6  # us per frame at 59.94 fps


def backward_anchors(fm, idx, moov_abs):
    hits = []
    for codec, kind in ((b'djmd', 1), (b'dbgi', 2)):
        ss = fm.tracks.get(codec, [])
        prev = None   # (i, abs, seq, ts)
        for i in range(len(ss) - 1, 0, -1):
            o, sz = ss[i]
            cands = idx.get((kind, sz, (o + fm.base_off) % CL), [])
            if prev is None:
                # last sample: the candidate closest before the moov
                cands = [c for c in cands if c[0] < moov_abs and moov_abs - c[0] < 64 * CL]
                if not cands:
                    continue
                c = max(cands, key=lambda c: c[0])
            else:
                di = prev[0] - i
                exp_ts = prev[3] - DT * di
                tol = DT * 0.45 + di * 40
                ok = [c for c in cands if abs(c[2] - exp_ts) < tol and 0 <= prev[2] - c[1] <= di * 1.1 + 8]
                if not ok:
                    continue
                c = min(ok, key=lambda c: abs(c[2] - exp_ts))
            prev = (i, c[0], c[1], c[2])
            hits.append((o, c[0]))
    for o, a in hits:
        fm.anchor.setdefault(fm.fc(o), set()).add(disk_cluster(a))
    fm.anchor.setdefault(fm.fc(fm.mdat_end), set()).add(disk_cluster(moov_abs))
    return len(hits)


if __name__ == '__main__':
    sys.argv = [sys.argv[0], IMG, PAIRS, INDEX, NAMES, OUT]
    import plan_v4
    from card import HEADER_OVERRIDES
    P = json.load(open(PAIRS))
    # clips whose header cluster is gone: no ftyp found and no known header offset
    LOST = {mv['moov'] for mv in P['pairs'] if mv['ftyp'] is None and mv['moov'] not in HEADER_OVERRIDES}
    names = json.load(open(NAMES))
    idx = chain.load_index(INDEX)
    chains = pickle.load(open(PLAN + '.chains.pkl', 'rb'))
    taken_all = {}
    for m, bo, e, ch in chains:
        if m['moov'] in LOST:
            continue
        for d in ch:
            if d is not None:
                taken_all[d] = m['name']
    results = []
    for mv in P['pairs']:
        if mv['moov'] not in LOST:
            continue
        f, moov, bo, meta = plan_v4.load(mv, names)
        fm = chain.FileModel(moov, 0)
        n = backward_anchors(fm, idx, mv['moov'])
        anchors = chain.anchors_clean(fm)
        # drop anchors that collide with clusters of the recovered files
        clash = [k for k, d in anchors.items() if d in taken_all]
        for k in clash:
            del anchors[k]
        print(meta['name'], 'telemetry hits', n, 'anchored clusters', len(anchors), 'of', fm.nfc,
              'dropped (owned by other clips)', len(clash), flush=True)
        r = plan_v4.solve((mv, names, anchors, set(taken_all)))
        results.append(r)
    pickle.dump([(m, bo, e, c) for m, bo, e, c, _ in results], open(OUT + '.chains.pkl', 'wb'))
    json.dump([dict(m, **r) for m, bo, e, c, r in results], open(OUT + '.json', 'w'), indent=1, default=str)
