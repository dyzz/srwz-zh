/* Host driver for the player's stream core (copied verbatim from player.c by
 * tests/test_vocal_stream.py) on top of the host-built Tremor + seek.c.
 *
 *   vocal-stream ref SONG.ogg OUT.raw
 *       whole-file decode with stock vorbisfile callbacks (reference)
 *   vocal-stream play SONG.ogg OUT.raw FRAMES LOOP_START LOOP_END ONCE CRC N_OUT SEED
 *       feed the core through simulated disc reads (random latency and long
 *       stalls), collect N_OUT frames of 8 KiB packets. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ivorbisfile.h"

#define FILE_CHUNK 32768
int ov_raw_pcm_seek(OggVorbis_File *vf,ogg_int64_t raw,ogg_int64_t pos);
static volatile uint32_t telemetry[32];
static unsigned song_frames, song_loop_start, song_loop_end, song_once, song_gain, song_finished;
static short pcm[4096];
static int fill;
void arena_reset(void){}
#include "stream-under-test.inc"

static unsigned char *load(const char *path, long *size){
  FILE *f=fopen(path,"rb");if(!f){perror(path);exit(2);}
  fseek(f,0,SEEK_END);*size=ftell(f);fseek(f,0,SEEK_SET);
  unsigned char *b=malloc(*size);if(fread(b,1,*size,f)!=(size_t)*size)exit(2);fclose(f);return b;
}
static unsigned char *mem;static long mem_size,mem_pos;
static size_t mrd(void *p,size_t s,size_t n,void *u){(void)u;size_t want=s*n;if(mem_pos+(long)want>mem_size)want=mem_size-mem_pos;memcpy(p,mem+mem_pos,want);mem_pos+=want;return want/s;}
static int msk(void *u,ogg_int64_t o,int w){(void)u;long x=(w==0?0:w==1?mem_pos:mem_size)+o;if(x<0||x>mem_size)return -1;mem_pos=x;return 0;}
static long mtl(void *u){(void)u;return mem_pos;}

static unsigned long long rng_state;
static unsigned rnd(unsigned n){rng_state=rng_state*6364136223846793005ULL+1442695040888963407ULL;return (unsigned)(rng_state>>33)%n;}

int main(int argc,char **argv){
  if(argc<4)return 2;
  long size;unsigned char *song=load(argv[2],&size);
  FILE *out=fopen(argv[3],"wb");
  if(!strcmp(argv[1],"ref")){
    OggVorbis_File ref;mem=song;mem_size=size;mem_pos=0;
    ov_callbacks cb={mrd,msk,0,mtl};
    if(ov_open_callbacks((void*)1,&ref,0,0,cb)<0){puts("ref open failed");return 1;}
    char buf[8192];int sec;long n;
    while((n=ov_read(&ref,buf,sizeof buf,&sec))>0)fwrite(buf,1,n,out);
    printf("frames %lld\n",(long long)ov_pcm_total(&ref,-1));
    ov_clear(&ref);fclose(out);return 0;
  }
  if(argc<11)return 2;
  song_frames=strtoul(argv[4],0,0);song_loop_start=strtoul(argv[5],0,0);song_loop_end=strtoul(argv[6],0,0);
  song_once=strtoul(argv[7],0,0);unsigned crc=strtoul(argv[8],0,0);unsigned long long n_out=strtoull(argv[9],0,0);
  rng_state=strtoull(argv[10],0,0);song_gain=65536;
  stream_reset((unsigned)size);
  int pending=0,wait=0;unsigned at=0,len=0;unsigned long long got=0;long idle=0;unsigned reads=0,stalls=0;
  telemetry[13]=0;
  while(got<n_out){
    int progress=0;
    if(!pending&&stream_next(&at,&len)){
      pending=1;wait=rnd(100)<15?60+rnd(240):rnd(4); /* frequent long disc stalls (battle loading) */
      if(wait>=60)stalls++;
    }
    if(pending&&wait--<=0){
      pending=0;reads++;
      int e=stream_feed(at,song+at,len,crc);if(e){printf("feed error %d\n",e);return 1;}
      progress=1;
    }
    if(!opened){
      int e=stream_open();if(e<0){printf("open error %d\n",e);return 1;}
      if(e){progress=1;telemetry[13]=0;}
    }else{
      int r=decode_pcm();
      if(r<0){printf("decode error %d at frame %u\n",r,telemetry[13]);return 1;}
      if(r>0){fwrite(pcm,1,8192,out);got+=2048;fill=0;progress=1;}
    }
    if(progress)idle=0;else if(++idle>100000){printf("stuck at frame %u pending %d\n",telemetry[13],pending);return 1;}
  }
  fclose(out);
  printf("ok reads %u stalls %u loops %u crc_state %u ring %u loop_off %u loop_len %u\n",reads,stalls,telemetry[14],crc_state,RING_BYTES,loop_off,loop_len);
  return 0;
}
