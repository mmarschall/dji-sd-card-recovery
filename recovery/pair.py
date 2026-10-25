import sys, os, re, json, struct, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mp4lib import *
from card import CL
IMG=sys.argv[1]; SCAN=sys.argv[2]
f=open(IMG,'rb')
ftyps=[];moovs=[]
for l in open(SCAN):
    m=re.match(r"(ftyp|moov) clus=\d+ off=\d+ abs=(\d+) size=(\d+) next=(.*)",l)
    if not m: continue
    t,a,sz,nx=m.group(1),int(m.group(2)),int(m.group(3)),m.group(4)
    if t=='ftyp' and 'isom' in nx: ftyps.append(a)
    if t=='moov' and 'mvhd' in nx: moovs.append((a,sz))
def mp4time(s): return datetime.datetime(1904,1,1)+datetime.timedelta(seconds=s)
F={}
for a in ftyps:
    f.seek(a); h=f.read(600)
    mds=None; o=0
    while o+16<=len(h):
        raw,t=struct.unpack_from('>I4s',h,o)
        if raw==1: raw=struct.unpack_from('>Q',h,o+8)[0]
        if t==b'mdat': mds=(o,raw); break
        if raw<8: break
        o+=raw
    F[a]=mds
M=[]
for a,sz in moovs:
    f.seek(a); m=f.read(sz)
    o=m.find(b'mvhd'); ver=m[o+4]
    ct=struct.unpack_from('>I',m,o+8)[0] if ver==0 else struct.unpack_from('>Q',m,o+8)[0]
    tr=parse_tracks(m); v=[d for d in tr if d.get('hdlr')==b'vide']
    end=max(o2+s2 for d in tr for o2,s2 in samples(d))
    first=min(o2 for d in tr for o2,s2 in samples(d))
    nfr=len(v[0]['sizes']) if v else 0
    M.append(dict(moov=a,size=sz,created=str(mp4time(ct)),mdat_end=end,first=first,frames=nfr))
used=set()
for mv in M:
    cand=[a for a,md in F.items() if md and md[0]+md[1]==mv['mdat_end'] and a<mv['moov'] and a not in used]
    # choose nearest preceding
    cand.sort(key=lambda a: mv['moov']-a)
    mv['ftyp']=cand[0] if cand else None
    if cand: used.add(cand[0])
    mv['gap_clusters']=((mv['moov']-mv['ftyp'])-mv['mdat_end'])//CL if cand else None
orph=[(a,F[a]) for a in ftyps if a not in used]
json.dump({'pairs':M,'orphan_ftyp':orph},open(sys.argv[3],'w'),indent=1)
for mv in M: print(mv['created'],mv['frames'],'ftyp',mv['ftyp'],'moov',mv['moov'],'gap',mv['gap_clusters'])
print('orphan ftyps:',orph)
