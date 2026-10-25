"""Greedy, decode-guided gap filling.

A wrong cluster inside a slice makes the HEVC decoder lose CABAC sync; the
rest of that slice is left undecoded (all-zero YUV = flat green). Picking the
gap clusters one at a time in allocation order and keeping the candidate that
leaves the least undecoded area recovers the original order.
"""
import subprocess, bisect
from mp4lib import parse_tracks
from mp4lib import hvcc_params

W, H = 480, 270


class Decoder:
    def __init__(self, moov):
        v = [d for d in parse_tracks(moov) if d['hdlr'] == b'vide'][0]
        self.keys = [x - 1 for x in v['stss']]
        self.params = hvcc_params(moov)

    @staticmethod
    def annexb(fm, f, o, sz):
        b = fm.read(f, o, sz)
        out = []
        p = 0
        while p + 4 <= len(b):
            L = int.from_bytes(b[p:p + 4], 'big')
            if L < 1 or p + 4 + L > len(b):
                out.append(b'\0\0\0\1' + b[p + 4:])
                break
            out.append(b'\0\0\0\1' + b[p + 4:p + 4 + L])
            p += 4 + L
        return b''.join(out)

    def frames(self, fm, f, first, last):
        """decode from the keyframe before `first` through `last`; returns (k0, [yuv420p frames])"""
        k = self.keys[max(0, bisect.bisect_right(self.keys, first) - 1)]
        st = self.params + b''.join(self.annexb(fm, f, o, s) for o, s in fm.video[k:last + 1])
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'quiet', '-threads', '4', '-f', 'hevc', '-i', '-',
                            '-vf', 'scale=%d:%d:flags=neighbor,format=yuv420p' % (W, H),
                            '-f', 'rawvideo', '-'], input=st, capture_output=True)
        fs = W * H * 3 // 2
        return k, [r.stdout[i:i + fs] for i in range(0, len(r.stdout) - fs + 1, fs)]


def green(frame):
    """number of chroma samples that are (near) zero in both U and V: undecoded area"""
    ys = W * H
    cs = ys // 4
    u = frame[ys:ys + cs]
    v = frame[ys + cs:ys + 2 * cs]
    return sum(1 for a, b in zip(u, v) if (a < 16 and b < 16) or (a > 239 and b > 239))


def tear(a, b):
    """worst 10-row luma band difference between consecutive frames"""
    best = 0
    bw = W * 10
    for s in range(0, W * H, bw):
        x = a[s:s + bw]
        y = b[s:s + bw]
        best = max(best, sum(abs(p - q) for p, q in zip(x, y)) / len(x))
    return best


def score(dec, fm, f, first, last):
    k, fr = dec.frames(fm, f, first, last)
    want = last - k + 1
    if len(fr) < want:
        return (10**9, 0)
    g = sum(green(fr[i]) for i in range(first - k, want))
    t = sum(tear(fr[i], fr[i - 1]) for i in range(max(1, first - k), want))
    return (g, t)


def fill_gap(dec, fm, f, ka, kb, n, free, CL, per_step=48):
    """choose n clusters from `free` (ascending) for file clusters ka+1..kb-1"""
    lo_o = (ka + 1) * CL - fm.base_off
    hi_o = kb * CL - fm.base_off
    starts = [o for o, _ in fm.video]
    vids = [i for i, (o, s) in enumerate(fm.video) if o < hi_o and o + s > lo_o]
    if not vids:
        for j in range(n):
            fm.clusters[ka + 1 + j] = free[j] if j < len(free) else None
        return 'no-video', []
    chosen = []
    pos = 0
    for j in range(n):
        need_after = n - j - 1
        cands = free[pos:len(free) - need_after][:per_step]
        results = []
        for ci, c in enumerate(cands):
            fm.clusters[ka + 1 + j] = c
            rest = free[pos + ci + 1:pos + ci + 1 + need_after]
            for t, d in enumerate(rest):
                fm.clusters[ka + 2 + j + t] = d
            # frames whose bytes touch this cluster
            co = (ka + 1 + j) * CL - fm.base_off
            touch = [i for i in vids if fm.video[i][0] < co + CL and sum(fm.video[i]) > co]
            if not touch:
                touch = vids[:1]
            results.append((score(dec, fm, f, touch[0], touch[-1]), ci, c))
        results.sort()
        (_, _), ci, c = results[0]
        chosen.append(c)
        pos = pos + ci + 1
        fm.clusters[ka + 1 + j] = c
    return 'greedy', chosen
