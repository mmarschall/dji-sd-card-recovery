"""Index every djmd/dbgi sample on the card: (abs, kind, len, seq, ts) -> binary records."""
import sys, os, re, struct
IMG=sys.argv[1]; OUT=sys.argv[2]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from card import HEAP, CL, NCL as N
def varint(b,p):
    v=0;s=0
    while p<len(b):
        x=b[p]; v|=(x&0x7f)<<s; p+=1; s+=7
        if not x&0x80: return v,p
    return None,p
DJ=re.compile(rb'\x1a[\x80-\xff][\x00-\x7f]\x0a[\x05-\x0c]\x08',re.S)
DB=re.compile(rb'\x12[\x80-\xff][\x00-\x7f]\x0a[\x80-\xff][\x00-\x7f]\x0a[\x05-\x0c]\x10',re.S)
REC=struct.Struct('<qBiiq')
f=open(IMG,'rb'); o=open(OUT,'wb'); n=0
CH=CL*512; f.seek(HEAP); pos=HEAP; carry=b''
end=HEAP+N*CL
while pos<end:
    b=f.read(min(CH,end-pos)); buf=carry+b; base=pos-len(carry)
    lim=len(buf)-64 if pos+len(b)<end else len(buf)
    for m in DJ.finditer(buf,0,lim):
        p=m.start(); L,q=varint(buf,p+1); seq,q2=varint(buf,p+6)
        if seq is None or q2>=len(buf) or buf[q2]!=0x10: continue
        ts,_=varint(buf,q2+1)
        if ts is None: continue
        o.write(REC.pack(base+p,1,q-p+L,seq,ts)); n+=1
    for m in DB.finditer(buf,0,lim):
        p=m.start(); L,q=varint(buf,p+1); ts,q2=varint(buf,p+9)
        if ts is None or q2>=len(buf) or buf[q2]!=0x18: continue
        seq,_=varint(buf,q2+1)
        if seq is None: continue
        o.write(REC.pack(base+p,2,q-p+L,seq,ts)); n+=1
    carry=buf[lim:]; pos+=len(b)
    if ((pos-HEAP)//CH)%40==0: print('%.1f%% records=%d'%(100*(pos-HEAP)/(N*CL),n),flush=True)
print('done records=%d'%n)
