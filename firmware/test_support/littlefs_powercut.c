#include "lfs.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define SIZE 0x1e0000
static unsigned char disk[SIZE],baseline[SIZE],bytes[240128];
static int cut=-1,mutations=0,failed=0;
static int rd(const struct lfs_config*c,lfs_block_t b,lfs_off_t o,void*p,lfs_size_t n){(void)c;assert(b*4096+o+n<=SIZE);memcpy(p,disk+b*4096+o,n);return 0;}
static int pg(const struct lfs_config*c,lfs_block_t b,lfs_off_t o,const void*p,lfs_size_t n){(void)c;if(failed)return LFS_ERR_IO;assert(b*4096+o+n<=SIZE);int fail=mutations++==cut;const unsigned char*s=p;unsigned char*d=disk+b*4096+o;for(unsigned i=0;i<(fail?n/2:n);i++){assert((d[i]&s[i])==s[i]);d[i]&=s[i];}if(fail){failed=1;return LFS_ERR_IO;}return 0;}
static int er(const struct lfs_config*c,lfs_block_t b){(void)c;if(failed)return LFS_ERR_IO;assert(b*4096+4096<=SIZE);int fail=mutations++==cut;memset(disk+b*4096,255,fail?2048:4096);if(fail){failed=1;return LFS_ERR_IO;}return 0;}
static int sy(const struct lfs_config*c){(void)c;return failed?LFS_ERR_IO:0;}
static struct lfs_config cfg={.read=rd,.prog=pg,.erase=er,.sync=sy,.read_size=128,.prog_size=128,.block_size=4096,.block_count=SIZE/4096,.block_cycles=512,.cache_size=512,.lookahead_size=128};
static int writefile(lfs_t*l,const char*name,unsigned count,unsigned char fill){lfs_file_t f;int r=lfs_file_open(l,&f,name,LFS_O_WRONLY|LFS_O_CREAT|LFS_O_TRUNC);if(r)return r;memset(bytes,fill,count);lfs_ssize_t n=lfs_file_write(l,&f,bytes,count);int sync=lfs_file_sync(l,&f);int close=lfs_file_close(l,&f);return n==(int)count&&sync==0&&close==0?0:-1;}
static int update(lfs_t*l){if(writefile(l,"cue0.tmp",240128,0x5a))return -1;return lfs_rename(l,"cue0.tmp","cue0.bin");}
static void verify(lfs_t*l){lfs_file_t f;assert(!lfs_file_open(l,&f,"cue0.bin",LFS_O_RDONLY));int size=lfs_file_size(l,&f);assert(size==53888||size==240128);assert(lfs_file_read(l,&f,bytes,size)==size);for(int i=0;i<size;i++)assert(bytes[i]==(size==53888?0x33:0x5a));assert(!lfs_file_close(l,&f));}
int main(void){lfs_t l;memset(disk,255,sizeof(disk));assert(!lfs_format(&l,&cfg));assert(!lfs_mount(&l,&cfg));unsigned sizes[]={53760,69148,86428,86428,57628,63388,84508,67228,84508,74908,94108,99868,115228,109468};for(unsigned i=0;i<14;i++){char name[24];snprintf(name,sizeof(name),"cue%u.bin",i);assert(!writefile(&l,name,sizes[i]+128,0x33));}assert(!lfs_unmount(&l));memcpy(baseline,disk,SIZE);mutations=0;assert(!lfs_mount(&l,&cfg));assert(!update(&l));int ops=mutations;verify(&l);assert(!lfs_unmount(&l));for(int i=0;i<ops;i++){memcpy(disk,baseline,SIZE);failed=0;cut=i;mutations=0;assert(!lfs_mount(&l,&cfg));(void)update(&l);lfs_unmount(&l);cut=-1;failed=0;assert(!lfs_mount(&l,&cfg));verify(&l);assert(!lfs_unmount(&l));}printf("LittleFS: %d torn-write/erase cut points; old-or-new valid file survives remount; 14-cue capacity PASS\n",ops);}
