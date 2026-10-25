"""Dump exFAT directory entries (live and deleted) of the given clusters.
usage: dirdump.py IMG CLUSTER [CLUSTER ...]"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from card import HEAP, CL, NCL as N
IMG = sys.argv.pop(1)
f=open(IMG,'rb')
def ts(v):
    d=v>>16; t=v&0xffff
    return '%04d-%02d-%02d %02d:%02d:%02d'%((d>>9)+1980,(d>>5)&15,d&31,t>>11,(t>>5)&63,(t&31)*2)
for c in map(int,sys.argv[1:]):
    f.seek(HEAP+(c-2)*CL); b=f.read(CL)
    print('== cluster',c)
    name=''
    for i in range(0,CL,32):
        e=b[i:i+32]; t=e[0]
        if t==0: print('  end',i//32); break
        if t&0x7f==0x05:
            if name: print('   ->',name); name=''
            print('  %3d %s FILE attr=%04x sec=%d created=%s modified=%s'%(i//32,'live' if t&0x80 else 'DEL ',int.from_bytes(e[4:6],'little'),e[1],ts(int.from_bytes(e[8:12],'little')),ts(int.from_bytes(e[12:16],'little'))))
        elif t&0x7f==0x40:
            print('  %3d      STREAM flags=%02x namelen=%d validlen=%d firstclus=%d len=%d'%(i//32,e[1],e[3],int.from_bytes(e[8:16],'little'),int.from_bytes(e[20:24],'little'),int.from_bytes(e[24:32],'little')))
        elif t&0x7f==0x41:
            name+=e[2:32].decode('utf-16le','replace').rstrip('\x00')
        else:
            print('  %3d      ?? %s'%(i//32,e.hex()))
    if name: print('   ->',name)
