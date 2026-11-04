#include "voice_cue_opus.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned seed=7243;
static unsigned rnd(void){seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;}
int main(int argc,char **argv){unsigned cases=0;for(int f=1;f<argc;f++){
 FILE *in=fopen(argv[f],"rb");assert(in);fseek(in,0,SEEK_END);size_t n=ftell(in);rewind(in);
 unsigned char *src=malloc(n);assert(fread(src,1,n,in)==n);fclose(in);voice_cue_opus_t o;
 assert(voice_cue_opus_parse(src,n,&o));
 for(size_t len=0;len<n;len++){unsigned char *p=malloc(len?len:1);memcpy(p,src,len);assert(!voice_cue_opus_parse(p,len,&o));free(p);cases++;}
 for(unsigned i=0;i<10000;i++){size_t len=rnd()%(n+40);unsigned char *p=calloc(len?len:1,1);memcpy(p,src,len<n?len:n);
 for(unsigned k=0;k<8 && len;k++)p[rnd()%len]=(unsigned char)rnd();
 if(voice_cue_opus_parse(p,len,&o)){const uint8_t *packet;size_t bytes;while(o.packet<o.count)assert(voice_cue_opus_next(&o,p,len,&packet,&bytes));assert(o.offset==len);}
 free(p);cases++;}free(src);
 }printf("ASan/UBSan parser: %u truncated/mutated cases PASS\n",cases);}
