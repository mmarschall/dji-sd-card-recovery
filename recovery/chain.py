"""Cluster-chain reconstruction for DJI MP4s on a damaged exFAT card.

Phase A  anchors: every djmd/dbgi sample (frame number + timestamp + exact size)
         pins its file cluster to a disk cluster, using the global metaindex.
Phase B  ownership: union of all anchored clusters of all files.
Phase C  fill: clusters between anchors are contiguous when the distance fits,
         otherwise the next clusters not owned by any other file (exFAT
         allocates free clusters in ascending order); checked with NAL chains.
"""
import sys, os, struct, bisect, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mp4lib import parse_tracks, samples

from card import CL, HEAP, NCL
REC = struct.Struct('<qBiiq')


def load_index(path):
    """(kind, length, offset-in-cluster) -> [(abs, seq, ts)]"""
    idx = {}
    with open(path, 'rb') as f:
        data = f.read()
    for a, kind, ln, seq, ts in REC.iter_unpack(data):
        idx.setdefault((kind, ln, (a - HEAP) % CL), []).append((a, seq, ts))
    return idx


def disk_cluster(a):
    return (a - HEAP) // CL + 2


def cluster_abs(c):
    return HEAP + (c - 2) * CL


class FileModel:
    def __init__(self, moov, base_off=0):
        self.moov = moov
        self.base_off = base_off
        tr = parse_tracks(moov)
        self.tracks = {d['codec']: list(samples(d)) for d in tr}
        self.video = self.tracks[b'hvc1']
        self.all = sorted((o, s, c) for c, ss in self.tracks.items() for o, s in ss)
        self.mdat_end = max(o + s for o, s, _ in self.all)
        self.nfc = (self.mdat_end + base_off + CL - 1) // CL
        self.clusters = [None] * self.nfc
        self.anchor = {}

    def fc(self, o):
        return (o + self.base_off) // CL

    # ---- reading through the chain ----
    def read(self, f, o, n):
        out = []
        o += self.base_off
        while n > 0:
            k = o // CL
            take = min(n, CL - o % CL)
            d = self.clusters[k] if k < self.nfc else None
            if d is None:
                out.append(b'\0' * take)
            else:
                f.seek(cluster_abs(d) + o % CL)
                out.append(f.read(take))
            o += take
            n -= take
        return b''.join(out)


def nal_valid(fm, f, o, sz):
    pos = 0
    n = 0
    while pos < sz:
        h = fm.read(f, o + pos, 6)
        L = int.from_bytes(h[:4], 'big')
        if L < 2 or pos + 4 + L > sz or h[4] & 0x81 or h[5] & 0xF8 or not h[5] & 7:
            return False
        pos += 4 + L
        n += 1
        if n > 64:
            return False
    return True


def phase_a(fm, idx, known_base=None, start_abs=None):
    """anchor clusters from telemetry samples (size + in-cluster offset + timestamp continuity)"""
    hits = []
    for codec, kind in ((b'djmd', 1), (b'dbgi', 2)):
        ss = fm.tracks.get(codec, [])
        prev = None          # (abs, seq, ts)
        for i, (o, sz) in enumerate(ss):
            if i == 0:
                continue
            cands = idx.get((kind, sz, (o + fm.base_off) % CL), [])
            if prev is not None:
                ok = [c for c in cands if 0 < c[2] - prev[2] < 400000 and 0 < c[1] - prev[1] < 64]
            else:
                ref = known_base if known_base is not None else start_abs
                ok = sorted(cands, key=lambda c: (c[0] < ref, abs(c[0] - ref))) if ref is not None else list(cands)
                ok = ok[:1] if ref is not None or len(ok) == 1 else []
            if len(ok) > 1:
                ok.sort(key=lambda c: abs(c[2] - prev[2] - 16683 * (c[1] - prev[1])))
                if abs(ok[0][2] - ok[1][2]) < 1000:
                    continue
            if not ok:
                continue
            prev = ok[0]
            hits.append((o, prev[0], kind))
    for o, a, kind in hits:
        fm.anchor.setdefault(fm.fc(o), set()).add(disk_cluster(a))
    if known_base is not None:
        fm.anchor.setdefault(0, set()).add(disk_cluster(known_base))
    return hits


def anchors_clean(fm):
    """resolve conflicting anchors per file cluster (majority / monotone)"""
    out = {}
    for k, ds in fm.anchor.items():
        if len(ds) == 1:
            out[k] = next(iter(ds))
    # drop anchors that break monotonic order with both neighbours
    ks = sorted(out)
    good = {}
    for i, k in enumerate(ks):
        d = out[k]
        lo = out[ks[i - 1]] if i > 0 else -1
        hi = out[ks[i + 1]] if i + 1 < len(ks) else 10**9
        if lo < d < hi or (i > 0 and i + 1 < len(ks) and (lo < d or d < hi)):
            good[k] = d
    return good


def phase_c(fm, f, owned_by_others, anchors, max_combo=20000, scorer=None):
    """fill all clusters in two passes; returns list of gap reports"""
    ks = sorted(anchors)
    for k in ks:
        fm.clusters[k] = anchors[k]
    pending = []
    # pass 1: everything that is determined by distance or by the free-cluster count
    for ka, kb in zip(ks, ks[1:]):
        da, db = anchors[ka], anchors[kb]
        n = kb - ka - 1
        if n == 0:
            continue
        if db - da == kb - ka and not any((da + j) in owned_by_others for j in range(1, n + 1)):
            for j in range(1, n + 1):
                fm.clusters[ka + j] = da + j
            continue
        free = [c for c in range(da + 1, db) if c not in owned_by_others] if db > da else []
        if len(free) == n:
            for j, c in enumerate(free):
                fm.clusters[ka + 1 + j] = c
            continue
        # provisional: allocation order
        for j in range(n):
            fm.clusters[ka + 1 + j] = free[j] if j < len(free) else None
        pending.append((ka, kb, n, free))
    if ks:
        for k in range(ks[0]):
            fm.clusters[k] = None
        last = ks[-1]
        for k in range(last + 1, fm.nfc):
            fm.clusters[k] = anchors[last] + (k - last)
    # pass 2: ambiguous gaps, validated against already filled neighbours
    issues = []
    for ka, kb, n, free in pending:
        lo_o = (ka + 1) * CL - fm.base_off
        hi_o = kb * CL - fm.base_off
        vids = [(o, s) for o, s in fm.video if o < hi_o and o + s > lo_o]
        ok = []
        if len(free) >= n:
            for t, combo in enumerate(itertools.combinations(free, n)):
                if t >= max_combo:
                    break
                for j, c in enumerate(combo):
                    fm.clusters[ka + 1 + j] = c
                if all(nal_valid(fm, f, o, s) for o, s in vids):
                    ok.append(combo)
                    if len(ok) > 8:
                        break
        if len(ok) == 1:
            pick, res = ok[0], 'unique-by-nal'
        elif len(ok) > 1 and scorer is not None:
            scores = []
            for combo in ok:
                for j, c in enumerate(combo):
                    fm.clusters[ka + 1 + j] = c
                scores.append((scorer(fm, f, vids), combo))
            scores.sort()
            pick, res = scores[0][1], 'by-decode %.1f vs %.1f' % (scores[0][0], scores[1][0])
        elif len(ok) > 1:
            pick, res = ok[0], 'multi'
        else:
            pick, res = (free[:n] if len(free) >= n else None), 'none'
        for j in range(n):
            fm.clusters[ka + 1 + j] = pick[j] if pick else None
        issues.append(dict(ka=ka, kb=kb, n=n, free=len(free), result=res, video=[o for o, _ in vids]))
    return issues


def verify(fm, f):
    bad = [o for o, s in fm.video if not nal_valid(fm, f, o, s)]
    return bad
