#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <debug.h>
#include <kernel.h>
#include "ivorbisfile.h"
extern unsigned char song_start[],song_end[];
volatile uint32_t result[12] = {0x564f5242};
static unsigned char pcm[4096];
static size_t pos;
static size_t rd(void *p,size_t s,size_t n,void *unused){
 if(!s)return 0;size_t left=(size_t)(song_end-song_start)-pos; if(n>left/s)n=left/s;
 memcpy(p,song_start+pos,n*s);pos+=n*s;return n;
}
static int sk(void *unused,ogg_int64_t off,int whence){
 ogg_int64_t x=(whence==SEEK_SET?0:whence==SEEK_CUR?pos:song_end-song_start)+off;
 if(x<0 || x>song_end-song_start)return -1;pos=x;return 0;
}
static long tl(void *unused){return pos;}
static uint32_t count(void){uint32_t x;__asm__ volatile("mfc0 %0,$9":"=r"(x));return x;}
int main(void){
 init_scr();scr_printf("Tremor EE decode benchmark\n");result[1]=1;
 OggVorbis_File vf;ov_callbacks cb={rd,sk,0,tl};int err=ov_open_callbacks((void*)1,&vf,0,0,cb);result[2]=err;
 if(err<0){result[1]=0xff;for(;;){} }
 vorbis_info *vi=ov_info(&vf,-1);result[7]=vi->channels;result[8]=vi->rate;result[1]=2;
 uint32_t hash=2166136261u;uint64_t cycles=0,bytes=0;int section=0;long n;
 for(;;){uint32_t before=count();n=ov_read(&vf,(char*)pcm,sizeof(pcm),&section);cycles+=(uint32_t)(count()-before);
  if(n<=0)break;
  for(long i=0;i<n;i++)hash=(hash^pcm[i])*16777619u;
  bytes+=n;result[3]=bytes/4;
 }
 result[2]=n;result[4]=hash;result[5]=(uint32_t)cycles;result[6]=cycles>>32;ov_clear(&vf);result[1]=n<0?0xfe:3;
 scr_printf("done frames=%u hash=%08x cycles=%u:%u\n",result[3],result[4],result[6],result[5]);
 for(;;){SleepThread();}
}
