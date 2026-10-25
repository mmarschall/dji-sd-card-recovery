"""Card geometry and per-card overrides.

All scripts read these values from a JSON file: $CARD_CONFIG, or ./card.json.
Create it from the image (MBR partition table + exFAT boot sector):

    python3 recovery/card.py IMG > card.json

Optional key "header_overrides": {"<moov offset>": <header offset>} for clips
whose header does not start on a cluster boundary (seen once: the camera's
power-loss repair wrote a header 8 bytes into its cluster).
"""
import sys, os, json, struct


def geometry(img):
    with open(img, 'rb') as f:
        mbr = f.read(512)
        part = 0
        if mbr[510:512] == b'\x55\xaa' and mbr[3:11] != b'EXFAT   ':
            part = struct.unpack_from('<I', mbr, 446 + 8)[0]   # first partition, start LBA
        f.seek(part * 512)
        bs = f.read(512)
    if bs[3:11] != b'EXFAT   ':
        sys.exit('no exFAT boot sector found')
    heap_sec, clusters = struct.unpack_from('<II', bs, 88)
    bps, spc = 1 << bs[108], 1 << bs[109]
    return dict(heap_offset=(part + heap_sec) * bps, cluster_size=bps * spc, cluster_count=clusters,
                header_overrides={})


def load():
    path = os.environ.get('CARD_CONFIG', 'card.json')
    if not os.path.exists(path):
        sys.exit('missing %s: create it with "python3 recovery/card.py IMG > card.json"' % path)
    c = json.load(open(path))
    c['header_overrides'] = {int(k): v for k, v in c.get('header_overrides', {}).items()}
    return c


if __name__ == '__main__':
    print(json.dumps(geometry(sys.argv[1]), indent=1))
else:
    _c = load()
    HEAP = _c['heap_offset']
    CL = _c['cluster_size']
    NCL = _c['cluster_count']
    HEADER_OVERRIDES = _c['header_overrides']
