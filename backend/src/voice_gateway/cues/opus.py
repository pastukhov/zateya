"""Fixed VCOPUS1 cue container; raw Opus packets, never Ogg.

Header32LE: magic8,version:u16,channels:u16,rate:u32,samples:u32,
preskip:u16,frame_samples:u16,packet_count:u16,reserved:u16,bitrate:u32.
Each packet is u16LE length + raw Opus. All sample counts are at24kHz.
"""
import ctypes as C
import ctypes.util
import math
import struct
from functools import lru_cache

HEADER=struct.Struct('<8sHHIIHHHHI')
MAGIC=b'VCOPUS1\0'
MAX_BYTES=65536
FRAME=480

@lru_cache(maxsize=1)
def library():
    name=C.util.find_library('opus')
    if not name:raise RuntimeError('libopus unavailable')
    lib=C.CDLL(name)
    lib.opus_encoder_create.argtypes=[C.c_int,C.c_int,C.c_int,C.POINTER(C.c_int)];lib.opus_encoder_create.restype=C.c_void_p
    lib.opus_encoder_destroy.argtypes=[C.c_void_p]
    lib.opus_encoder_ctl.argtypes=[C.c_void_p,C.c_int];lib.opus_encoder_ctl.restype=C.c_int
    lib.opus_encode.argtypes=[C.c_void_p,C.POINTER(C.c_int16),C.c_int,C.POINTER(C.c_ubyte),C.c_int];lib.opus_encode.restype=C.c_int
    lib.opus_decoder_create.argtypes=[C.c_int,C.c_int,C.POINTER(C.c_int)];lib.opus_decoder_create.restype=C.c_void_p
    lib.opus_decoder_destroy.argtypes=[C.c_void_p]
    lib.opus_decode.argtypes=[C.c_void_p,C.c_void_p,C.c_int,C.POINTER(C.c_int16),C.c_int,C.c_int];lib.opus_decode.restype=C.c_int
    lib.opus_packet_get_nb_samples.argtypes=[C.c_void_p,C.c_int,C.c_int];lib.opus_packet_get_nb_samples.restype=C.c_int
    lib.opus_get_version_string.restype=C.c_char_p
    return lib


def parse_container(data):
    if not 34<=len(data)<=MAX_BYTES:raise ValueError('Invalid Opus size')
    magic,version,channels,rate,samples,skip,frame,count,reserved,bitrate=HEADER.unpack_from(data)
    if (magic,version,channels,rate,frame,reserved,bitrate)!=(MAGIC,1,1,24000,480,0,24000):raise ValueError('Invalid Opus format')
    if not 0<samples<=120000 or skip>960 or count!=math.ceil((samples+skip)/480) or not 0<count<=252:
        raise ValueError('Invalid Opus duration')
    packets=[];offset=32
    for _ in range(count):
        if offset+2>len(data):raise ValueError('Truncated packet length')
        size=struct.unpack_from('<H',data,offset)[0];offset+=2
        if not 2<=size<=1275 or offset+size>len(data):raise ValueError('Invalid Opus packet size')
        packet=data[offset:offset+size];offset+=size
        if library().opus_packet_get_nb_samples(packet,size,24000)!=480:raise ValueError('Invalid packet duration')
        packets.append(packet)
    if offset!=len(data):raise ValueError('Trailing Opus data')
    return dict(samples=samples,preskip=skip,frame_samples=480,packet_count=count),packets


def encode_pcm(pcm):
    if not pcm or len(pcm)%2 or len(pcm)>240000:raise ValueError('Invalid PCM cue')
    lib=library();err=C.c_int();encoder=lib.opus_encoder_create(24000,1,2049,C.byref(err))
    if not encoder or err.value:raise RuntimeError('Opus encoder create failed')
    try:
        for ctl,value in ((4002,24000),(4006,1),(4010,5)):
            if lib.opus_encoder_ctl(encoder,ctl,C.c_int(value)):raise RuntimeError('Opus configuration failed')
        lookahead=C.c_int()
        if lib.opus_encoder_ctl(encoder,4027,C.byref(lookahead)) or not 0<=lookahead.value<=960:
            raise RuntimeError('Invalid Opus lookahead')
        samples=len(pcm)//2;count=math.ceil((samples+lookahead.value)/480)
        source=pcm+b'\0'*(count*960-len(pcm));packets=[]
        output=(C.c_ubyte*1275)()
        for i in range(count):
            frame=(C.c_int16*480)(*struct.unpack_from('<480h',source,i*960))
            size=lib.opus_encode(encoder,frame,480,output,1275)
            if not 2<=size<=1275:raise RuntimeError('Opus encode failed')
            packets.append(struct.pack('<H',size)+bytes(output[:size]))
        encoded=HEADER.pack(MAGIC,1,1,24000,samples,lookahead.value,480,count,0,24000)+b''.join(packets)
        parse_container(encoded)
        return encoded
    finally:lib.opus_encoder_destroy(encoder)


def decode_container(data):
    meta,packets=parse_container(data);lib=library();error=C.c_int()
    decoder=lib.opus_decoder_create(24000,1,C.byref(error))
    if not decoder or error.value:raise RuntimeError('Opus decoder create failed')
    try:
        pcm=bytearray();frame=(C.c_int16*480)()
        for packet in packets:
            if lib.opus_decode(decoder,packet,len(packet),frame,480,0)!=480:raise ValueError('Invalid Opus data')
            pcm.extend(struct.pack('<480h',*frame))
        start=meta['preskip']*2
        return bytes(pcm[start:start+meta['samples']*2])
    finally:lib.opus_decoder_destroy(decoder)
