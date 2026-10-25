import struct
CONT={b'moov',b'trak',b'mdia',b'minf',b'stbl',b'udta',b'edts',b'dinf'}
def boxes(b,off=0,end=None):
    end=len(b) if end is None else end
    while off+8<=end:
        sz,t=struct.unpack_from('>I4s',b,off); h=8
        if sz==1: sz=struct.unpack_from('>Q',b,off+8)[0]; h=16
        if sz==0: sz=end-off
        if sz<8 or off+sz>end: return
        yield t,off,h,sz
        off+=sz
def find(b,path,off=0,end=None):
    for t,o,h,sz in boxes(b,off,end):
        if t==path[0]:
            if len(path)==1: yield o,h,sz
            else: yield from find(b,path[1:],o+h,o+sz)
def parse_tracks(m):
    """m = moov bytes (starting at moov box). returns list of track dicts"""
    tr=[]
    for o,h,sz in find(m,[b'moov',b'trak']):
        d={}
        for ho,hh,hs in find(m,[b'mdia',b'hdlr'],o+h,o+sz): d['hdlr']=m[ho+hh+8:ho+hh+12]
        for so,sh,ss in find(m,[b'mdia',b'minf',b'stbl'],o+h,o+sz):
            for t,bo,bh,bs in boxes(m,so+sh,so+ss):
                p=bo+bh
                if t==b'stsd': d['codec']=m[p+12:p+16]
                elif t==b'stsz':
                    ssz,cnt=struct.unpack_from('>II',m,p+4)
                    d['sizes']=[ssz]*cnt if ssz else list(struct.unpack_from('>%dI'%cnt,m,p+12))
                elif t==b'stco':
                    cnt=struct.unpack_from('>I',m,p+4)[0]; d['co']=list(struct.unpack_from('>%dI'%cnt,m,p+8))
                elif t==b'co64':
                    cnt=struct.unpack_from('>I',m,p+4)[0]; d['co']=list(struct.unpack_from('>%dQ'%cnt,m,p+8))
                elif t==b'stsc':
                    cnt=struct.unpack_from('>I',m,p+4)[0]; d['stsc']=[struct.unpack_from('>III',m,p+8+12*i) for i in range(cnt)]
                elif t==b'stss':
                    cnt=struct.unpack_from('>I',m,p+4)[0]; d['stss']=list(struct.unpack_from('>%dI'%cnt,m,p+8))
        tr.append(d)
    return tr
def samples(d):
    """yield (file_offset,size) for each sample"""
    co=d['co']; stsc=d['stsc']; sizes=d['sizes']; si=0
    for ci,off in enumerate(co):
        cn=ci+1; spc=None
        for first,n,_ in stsc:
            if first<=cn: spc=n
        for _ in range(spc):
            if si>=len(sizes): return
            yield off,sizes[si]; off+=sizes[si]; si+=1

def nal_ok(f,abs_off,size):
    """check that sample at abs_off of given size is a valid chain of length-prefixed HEVC NALs"""
    f.seek(abs_off); pos=0; n=0
    while pos<size:
        f.seek(abs_off+pos); h=f.read(6)
        if len(h)<6: return False
        L=int.from_bytes(h[:4],'big')
        if L<2 or pos+4+L>size: return False
        if h[4]&0x81 or h[5]&0xF8 or not h[5]&7: return False
        pos+=4+L; n+=1
        if n>64: return False
    return pos==size


def hvcc_params(moov):
    i=moov.find(b'hvcC'); p=i+4+22
    n=moov[p]; p+=1; out=b''
    for _ in range(n):
        p+=1; cnt=struct.unpack_from('>H',moov,p)[0]; p+=2
        for _ in range(cnt):
            L=struct.unpack_from('>H',moov,p)[0]; p+=2
            out+=b'\0\0\0\1'+moov[p:p+L]; p+=L
    return out
