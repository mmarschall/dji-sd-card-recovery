import sys, os, mmap, re
IMG=sys.argv[1]; OUT=sys.argv[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from card import HEAP, CL, NCL as N
f=open(IMG,'rb'); m=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
o=open(OUT,'w')
CH=CL*512  # 64 MiB chunks
pat=re.compile(rb'moov|ftyp|mvhd|DJI_|\x85[\x02-\x12]..........\x00\x00.{16}\xc0', re.S)
zero=bytes(CL); nz=0
for start in range(HEAP, HEAP+N*CL, CH):
    end=min(start+CH+64, HEAP+N*CL)
    buf=m[start:end]
    for i in range(0,min(CH,len(buf)),CL):
        if buf[i:i+CL]==zero: nz+=1
    for mt in pat.finditer(buf):
        p=mt.start()
        if p>=CH: continue
        a=start+p; c=(a-HEAP)//CL+2; co=(a-HEAP)%CL
        t=mt.group()[:4]
        if t in (b'moov',b'ftyp'):
            sz=int.from_bytes(buf[p-4:p],'big') if p>=4 else -1
            o.write('%s clus=%d off=%d abs=%d size=%d next=%r\n'%(t.decode(),c,co,a-4,sz,buf[p+4:p+12]))
        elif t==b'mvhd': o.write('mvhd clus=%d off=%d abs=%d\n'%(c,co,a))
        elif t==b'DJI_': o.write('name clus=%d off=%d abs=%d %r\n'%(c,co,a,buf[p:p+40]))
        else:
            if co%32==0: o.write('dirent clus=%d off=%d\n'%(c,co))
    o.flush()
    if ((start-HEAP)//CH)%32==0: print('progress %.1f%% zero=%d'%(100*(start-HEAP)/(N*CL),nz),flush=True)
print('done zero=%d'%nz)
