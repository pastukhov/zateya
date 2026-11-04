"""Host transaction tests use the production C store and real hashlib SHA256.

POSIX fault injection verifies adapter-independent record/replace behavior;
LittleFS emulator and physical flash are separate validation layers.
"""
import ctypes as C
import hashlib
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
HASH=C.CFUNCTYPE(C.c_bool,C.c_void_p,C.c_size_t,C.c_void_p)

class Store(C.Structure):
    _fields_=[('root',C.c_char*128),('hash',HASH),('limit',C.c_size_t)]

class Record(C.Structure):
    _fields_=[('size',C.c_size_t),('sha',C.c_char*65),('codec',C.c_int)]

@pytest.fixture(scope='module')
def library(tmp_path_factory):
    root=tmp_path_factory.mktemp('cue-store-native');shim=root/'fault.c'
    shim.write_text('''#include <stdio.h>
#include <unistd.h>
static int fault;
void test_fault(int op){fault=op;}
extern size_t __real_fwrite(const void*,size_t,size_t,FILE*);
extern int __real_fclose(FILE*);
extern int __real_fsync(int);
extern int __real_rename(const char*,const char*);
size_t __wrap_fwrite(const void*p,size_t s,size_t n,FILE*f){if(fault==1){__real_fwrite(p,s,n/2,f);return n/2;}return __real_fwrite(p,s,n,f);}
int __wrap_fclose(FILE*f){int r=__real_fclose(f);return fault==2?EOF:r;}
int __wrap_fsync(int f){return fault==3?-1:__real_fsync(f);}
int __wrap_rename(const char*a,const char*b){return fault==4?-1:__real_rename(a,b);}
''')
    out=root/'store.so'
    subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Werror','-I'+str(ROOT/'firmware/include'),
        str(ROOT/'firmware/src/voice_cue_store.c'),str(ROOT/'firmware/src/voice_cue_cache.c'),str(ROOT/'firmware/src/voice_cue_opus.c'),str(shim),
        '-Wl,--wrap=fwrite,--wrap=fclose,--wrap=fsync,--wrap=rename','-o',str(out)],check=True)
    lib=C.CDLL(str(out))
    lib.voice_cue_store_init.argtypes=[C.POINTER(Store),C.c_char_p,HASH];lib.voice_cue_store_init.restype=C.c_bool
    lib.voice_cue_store_put.argtypes=[C.POINTER(Store),C.c_int,C.c_void_p,C.c_size_t,C.c_char_p];lib.voice_cue_store_put.restype=C.c_int
    lib.voice_cue_store_load.argtypes=[C.POINTER(Store),C.c_int,C.c_void_p,C.c_size_t,C.POINTER(Record)];lib.voice_cue_store_load.restype=C.c_bool
    return lib

@HASH
def digest(data,size,out):
    value=hashlib.sha256(C.string_at(data,size)).digest();C.memmove(out,value,32);return True

def init(lib,root):
    store=Store();assert lib.voice_cue_store_init(C.byref(store),str(root).encode(),digest);return store

def put(lib,store,pcm,name=0):
    return lib.voice_cue_store_put(C.byref(store),name,pcm,len(pcm),hashlib.sha256(pcm).hexdigest().encode())

def load(lib,store,name=0):
    data=C.create_string_buffer(240000);record=Record()
    valid=lib.voice_cue_store_load(C.byref(store),name,data,len(data),C.byref(record))
    return bytes(data[:record.size]) if valid else None

def test_restart_offline_same_hash_and_corrupt_records(library,tmp_path):
    lib=library;store=init(lib,tmp_path);pcm=b'\x01\0'*2000
    assert put(lib,store,pcm)==2
    file=tmp_path/'listening.vcue';stamp=file.stat().st_mtime_ns
    assert put(lib,store,pcm)==1 and file.stat().st_mtime_ns==stamp
    assert load(lib,init(lib,tmp_path))==pcm
    original=file.read_bytes()
    for bad in (b'bad',original[:-1],original+b'x',original[:128]+b'\0'*len(pcm)):
        file.write_bytes(bad);assert load(lib,store) is None
    file.write_bytes(original)
    assert load(lib,store)==pcm

@pytest.mark.parametrize('operation',[1,2,3,4])
def test_write_close_sync_and_rename_failures_preserve_old(library,tmp_path,operation):
    lib=library;store=init(lib,tmp_path);old=b'\x01\0'*100;new=b'\x02\0'*100
    assert put(lib,store,old)==2
    lib.test_fault(operation)
    try:assert put(lib,store,new)==0
    finally:lib.test_fault(0)
    assert load(lib,store)==old
    assert not (tmp_path/'listening.tmp').exists()

def test_full_cache_preserves_valid_records_and_unknown_files(library,tmp_path):
    lib=library;store=init(lib,tmp_path);pcm=b'\x01\0'*100
    assert put(lib,store,pcm)==2
    store.limit=len(pcm)+128
    assert put(lib,store,pcm,name=1)==0
    assert load(lib,store)==pcm
    foreign=tmp_path/'foreign.tmp';foreign.write_text('keep')
    lib.voice_cue_store_clean_temps(C.byref(store))
    assert foreign.read_text()=='keep'


def test_opus_record_retains_legacy_rollback_and_failed_replace(library,tmp_path):
    from backend.src.voice_gateway.cues.opus import encode_pcm
    lib=library;store=init(lib,tmp_path);pcm=b'\x01\0'*2000
    assert put(lib,store,pcm)==2
    legacy=(tmp_path/'listening.vcue').read_bytes()
    lib.voice_cue_store_put_codec.argtypes=lib.voice_cue_store_put.argtypes+[C.c_int]
    lib.voice_cue_store_put_codec.restype=C.c_int
    def encoded_put(data):
        return lib.voice_cue_store_put_codec(C.byref(store),0,data,len(data),hashlib.sha256(data).hexdigest().encode(),1)
    data=encode_pcm(pcm);assert encoded_put(data)==2
    original=(tmp_path/'listening.vopus').read_bytes()
    assert (tmp_path/'listening.vcue').read_bytes()==legacy and load(lib,store)==pcm
    lib.test_fault(4)
    try:assert encoded_put(encode_pcm(b'\0\0'*2400))==0
    finally:lib.test_fault(0)
    assert (tmp_path/'listening.vopus').read_bytes()==original
    assert encoded_put(data[:-1])==0
    wrong=bytearray(original);wrong[:8]=b'VCUEPCM1';wrong[8:12]=(1).to_bytes(4,'little');wrong[116:120]=bytes(4)
    (tmp_path/'listening.vopus').write_bytes(wrong)
    assert encoded_put(data)==2
    assert (tmp_path/'listening.vopus').read_bytes()==original
    store.limit=len(legacy)+128
    assert encoded_put(encode_pcm(b'\0\0'*3000))==0
