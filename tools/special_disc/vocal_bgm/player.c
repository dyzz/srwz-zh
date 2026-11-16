/* SP address template, relocated for Z/Best. Vorbis is loaded asynchronously.
 * Native Sony SIF entry points below require the asserted SLPS_259.20 preimages.
 * telemetry[28:29] show the bytes read from the song so far / its size.
 * No host audio or runtime file is used by the player.
 *
 * v6 keeps only a window of the song in EE memory (about 0.4 MiB instead of the
 * whole 4 MiB file), so the game's own heap stays large enough for the Special
 * Disc event gallery. Its big combination effects ran out of heap under v5.
 * Buffers:
 *   tail  the last 64 KiB, read first: Tremor scans it when opening the file;
 *   ring  a sliding window over [0, tail): reading stays LOOKAHEAD bytes ahead
 *         of the decoder, so a battle start does not compete with the game's
 *         own disc reads;
 *   loop  bytes from a page boundary passed LOOP_LEAD frames before the loop
 *         start. At the loop end the decoder restarts at that page and skips
 *         forward to the exact loop start (ov_raw_pcm_seek, seek.c) while the
 *         ring refills behind the loop buffer.
 * The body CRC is checked when the first pass has read the whole song; a loop
 * that ends earlier plays without that check. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "ivorbisfile.h"
extern unsigned char irx_start[],irx_end[];
int ov_raw_pcm_seek(OggVorbis_File *vf,ogg_int64_t raw,ogg_int64_t pos);
#define SONG_MAX (4*1024*1024)
#define FILE_CHUNK 32768
static unsigned song_frames, song_loop_start, song_loop_end, song_once, song_gain, song_finished;
static unsigned char metadata[18432] __attribute__((aligned(64)));
static unsigned io_reply[(FILE_CHUNK+64)/4] __attribute__((aligned(64)));
volatile uint32_t telemetry[32]={0x564f5231};
/* IOP-side counters (see iop/pcm.c), refreshed by every PCM request. */
volatile uint32_t iopstats[9];
static unsigned client[16] __attribute__((aligned(64)));
static unsigned reply[16] __attribute__((aligned(64)));
static short pcm[4096] __attribute__((aligned(64)));
static short packet[4096] __attribute__((aligned(64)));
static int ready,wanted,fill;
/* Disk RPCs use their own client, IOP server thread and persistent buffers. The
 * completion ISR only clears a flag; nothing waits for CD on the EE. */
static unsigned file_client[16] __attribute__((aligned(64)));
static unsigned file_args[2] __attribute__((aligned(64)));
static volatile int file_pending;
static int load_stage,close_pending,metadata_valid;
static unsigned load_track,load_at,load_count;
static unsigned requested_volume;

/* ---- stream core (host-tested: tests/test_vocal_stream.py compiles this part verbatim) ---- */
#define TAIL_BYTES 65536
#define TAIL_MAX (TAIL_BYTES+2048)
#define RING_BYTES (192*1024)
#define LOOP_BYTES (192*1024)
#define HEAD_START 65536
#define READ_MARGIN 16384
#define LOOKAHEAD (128*1024)
#define BACK_KEEP 32768
#define LOOP_LEAD (6*48000)
static unsigned char tail_buf[TAIL_MAX] __attribute__((aligned(64)));
static unsigned char ring[RING_BYTES] __attribute__((aligned(64)));
static unsigned char loop_buf[LOOP_BYTES] __attribute__((aligned(64)));
static OggVorbis_File vf;
static unsigned song_size,tail_off,tail_pos;
static int tail_done,opened,starved;
static unsigned ring_lo,ring_hi,open_head;
/* loop_state: 0 not chosen, 1 chosen (loop_buf holds [loop_off,loop_off+loop_len)), -1 failed */
static int loop_state;
static unsigned loop_off,loop_len,loop_need;
static unsigned crc_pos,load_crc,crc_state; /* crc_state: 0 running, 1 matched */
static size_t source_pos;
static unsigned crc_table[256];
static int crc_ready;
static void crc_init(void){if(!crc_ready){for(unsigned i=0;i<256;i++){unsigned c=i;for(int j=0;j<8;j++)c=(c>>1)^((0-(c&1))&0xedb88320u);crc_table[i]=c;}crc_ready=1;}}
static unsigned crc_step(unsigned crc,const unsigned char *data,unsigned n){for(unsigned i=0;i<n;i++)crc=crc_table[(crc^data[i])&255]^(crc>>8);return crc;}
static void ring_copy(unsigned char *dst,unsigned pos,unsigned n){
 unsigned at=pos%RING_BYTES,first=RING_BYTES-at;if(first>n)first=n;
 memcpy(dst,ring+at,first);if(n>first)memcpy(dst+first,ring,n-first);
}
/* Bytes readable at pos from one buffer without a gap; *where 0 tail, 1 loop, 2 ring. */
static unsigned segment(unsigned pos,int *where){
 if(tail_done&&pos>=tail_off&&pos<song_size){*where=0;return song_size-pos;}
 if(pos>=ring_lo&&pos<ring_hi){*where=2;return ring_hi-pos;}
 if(loop_state>0&&pos>=loop_off&&pos<loop_off+loop_len){*where=1;return loop_off+loop_len-pos;}
 return 0;
}
static unsigned avail_from(unsigned pos){
 unsigned total=0;int w;
 while(pos<song_size){unsigned n=segment(pos,&w);if(!n)break;total+=n;pos+=n;}
 return total;
}
static size_t rd(void *p,size_t s,size_t n,void *unused){
 (void)unused;if(!s)return 0;size_t want=n*s,got=0;unsigned char *dst=p;
 while(got<want&&source_pos<song_size){
  int w;unsigned k=segment(source_pos,&w);if(!k)break;if(k>want-got)k=want-got;
  if(w==0)memcpy(dst+got,tail_buf+(source_pos-tail_off),k);
  else if(w==1)memcpy(dst+got,loop_buf+(source_pos-loop_off),k);
  else ring_copy(dst+got,source_pos,k);
  got+=k;source_pos+=k;
 }
 if(got<want&&source_pos<song_size)starved=1;
 return got/s;
}
static int sk(void *unused,ogg_int64_t off,int whence){(void)unused;ogg_int64_t x=(whence==0?0:whence==1?(ogg_int64_t)source_pos:song_size)+off;if(x<0||x>song_size)return -1;source_pos=x;return 0;}
static long tl(void *unused){(void)unused;return source_pos;}
/* A new song of size bytes: tail first, then the ring from offset 0. */
static void stream_reset(unsigned size){
 if(opened){ov_clear(&vf);opened=0;}
 song_size=size;tail_off=size>2*TAIL_BYTES?((size-TAIL_BYTES)&~2047u):size;tail_pos=tail_off;tail_done=tail_off>=size;
 ring_lo=ring_hi=open_head=0;loop_state=0;loop_off=loop_len=loop_need=0;source_pos=0;starved=0;
 crc_init();crc_pos=0;load_crc=~0u;crc_state=0;
}
/* Lowest ring byte still needed. */
static unsigned ring_keep(void){
 if(!opened||source_pos<ring_lo||source_pos>ring_hi)return ring_lo;
 return source_pos-ring_lo>BACK_KEEP?source_pos-BACK_KEEP:ring_lo;
}
/* Next disc read, if one is wanted now. */
static int stream_next(unsigned *off,unsigned *len){
 if(!tail_done){*off=tail_pos;*len=song_size-tail_pos;if(*len>FILE_CHUNK)*len=FILE_CHUNK;return 1;}
 if(ring_hi>=tail_off)return 0;
 unsigned n=tail_off-ring_hi;if(n>FILE_CHUNK)n=FILE_CHUNK;
 if(ring_hi+n>ring_keep()+RING_BYTES)return 0;
 if(opened&&source_pos<tail_off&&ring_hi>=source_pos+LOOKAHEAD)return 0;
 *off=ring_hi;*len=n;return 1;
}
/* One completed read of [off,off+len). Returns 0, or 6 when the body CRC fails. */
static int stream_feed(unsigned off,const unsigned char *data,unsigned len,unsigned want_crc){
 if(!tail_done&&off==tail_pos){
  memcpy(tail_buf+(off-tail_off),data,len);tail_pos+=len;tail_done=tail_pos>=song_size;
 }else if(off==ring_hi&&off+len<=tail_off){
  unsigned at=off%RING_BYTES,first=RING_BYTES-at;if(first>len)first=len;
  memcpy(ring+at,data,first);if(len>first)memcpy(ring,data+first,len-first);
  ring_hi+=len;if(ring_hi-ring_lo>RING_BYTES)ring_lo=ring_hi-RING_BYTES;
  if(loop_state>0&&off<=loop_off+loop_len&&off+len>loop_off+loop_len&&loop_len<LOOP_BYTES){
   unsigned from=loop_off+loop_len-off,n=len-from;if(n>LOOP_BYTES-loop_len)n=LOOP_BYTES-loop_len;
   memcpy(loop_buf+loop_len,data+from,n);loop_len+=n;
  }
 }else return 0; /* a read issued before a loop jump: ignore */
 if(crc_state==0&&off==crc_pos&&off<tail_off){
  load_crc=crc_step(load_crc,data,len);crc_pos+=len;
  if(crc_pos>=tail_off&&tail_done){
   load_crc=crc_step(load_crc,tail_buf,song_size-tail_off);
   if((~load_crc)!=want_crc)return 6;
   crc_state=1;
  }
 }
 return 0;
}
void arena_reset(void);
/* Open once the tail and the head are in. 1 opened, 0 wait, <0 error. */
static int stream_open(void){
 unsigned need=tail_off<HEAD_START?tail_off:HEAD_START;
 if(!tail_done||ring_hi<need||ring_hi<=open_head)return 0;
 open_head=ring_hi;source_pos=0;starved=0;arena_reset();
 ov_callbacks cb={rd,sk,0,tl};int e=ov_open_callbacks((void*)1,&vf,0,0,cb);telemetry[8]=e;
 /* Headers or the last page may need bytes not read yet: retry after the next chunk. */
 if(e<0){if(starved&&ring_hi<tail_off&&ring_hi-ring_lo<RING_BYTES-FILE_CHUNK)return 0;return -7;}
 opened=1;vorbis_info *vi=ov_info(&vf,-1);telemetry[10]=vi->rate;telemetry[11]=vi->channels;
 if(!(vi->rate==48000&&vi->channels==2&&ov_streams(&vf)==1&&ov_pcm_total(&vf,-1)==song_frames))return -7;
 if(!song_once&&song_loop_start<LOOP_LEAD){
  loop_off=(unsigned)vf.dataoffsets[0];
  if(loop_off>=ring_lo&&loop_off<=ring_hi){loop_len=ring_hi-loop_off;if(loop_len>LOOP_BYTES)loop_len=LOOP_BYTES;ring_copy(loop_buf,loop_off,loop_len);loop_state=1;}
  else loop_state=-1;
 }
 return 1;
}
/* Before each read on the first pass: pick the loop page LOOP_LEAD frames early,
 * and note how far the loop start lies in bytes. */
static void stream_loop_track(unsigned frame){
 if(song_once)return;
 if(loop_state==0&&frame+LOOP_LEAD>=song_loop_start){
  unsigned off=(unsigned)vf.offset;
  if(off>=ring_lo&&off<=ring_hi){loop_off=off;loop_len=ring_hi-off;if(loop_len>LOOP_BYTES)loop_len=LOOP_BYTES;ring_copy(loop_buf,off,loop_len);loop_state=1;}
  else loop_state=-1;
 }
 if(loop_state>0&&!loop_need&&frame>=song_loop_start)loop_need=source_pos-loop_off+READ_MARGIN;
}
/* At the loop end: 1 jumped, 0 wait for bytes, <0 error. */
static int stream_loop_jump(void){
 if(loop_state<=0)return -8;
 /* A loop shorter than one read call: the first pass is here, past the loop start. */
 if(!loop_need)loop_need=source_pos-loop_off+READ_MARGIN;
 unsigned have=loop_off+loop_len>=tail_off&&tail_done?song_size-loop_off:loop_len;
 unsigned need=loop_need<song_size-loop_off?loop_need:song_size-loop_off;
 if(have<need){
  /* The capture still grows with the ring (contiguous until LOOP_BYTES). */
  if(loop_len<LOOP_BYTES&&loop_off+loop_len<tail_off)return 0;
  return -8;
 }
 unsigned next=loop_off+loop_len;
 if(next<tail_off){ring_lo=ring_hi=next;}else{ring_lo=ring_hi=tail_off;}
 if(ov_raw_pcm_seek(&vf,loop_off,song_loop_start)<0)return -8;
 return 1;
}
/* Decode into pcm until 8 KiB of frames are ready. 1 ready, 0 waiting for the
 * disc, <0 error (fallback reason). A partial buffer is kept. */
static int decode_pcm(void){
 int section=0;
 while(fill<8192){
  if(telemetry[13]>=song_loop_end){
   if(song_once){memset((char*)pcm+fill,0,8192-fill);fill=8192;song_finished=1;break;}
   int j=stream_loop_jump();if(j<=0){if(!j)telemetry[25]++;return j;}
   telemetry[23]=telemetry[13];telemetry[24]=telemetry[15];telemetry[14]++;
   telemetry[13]=song_loop_start;telemetry[15]=2166136261u;
  }
  if(source_pos<tail_off&&avail_from(source_pos)<READ_MARGIN&&source_pos+avail_from(source_pos)<tail_off){telemetry[25]++;return 0;}
  stream_loop_track(telemetry[13]);
  unsigned limit=(song_loop_end-telemetry[13])*4;if(limit>(unsigned)(8192-fill))limit=8192-fill;
  starved=0;long n=ov_read(&vf,(char*)pcm+fill,limit,&section);
  if(n<=0){if(starved){telemetry[25]++;return 0;}telemetry[8]=n?n:-101;return -8;}
  for(long k=0;k<n;k++)telemetry[15]=(telemetry[15]^((unsigned char*)pcm)[fill+k])*16777619u;
  fill+=n;telemetry[13]+=n/4;telemetry[26]+=n/4;
 }
 return 1;
}
/* ---- end of stream core ---- */

#define NATIVE ((int(*)(int,int))0x18c8a0)
static void fallback(unsigned reason);
static int init(void);
static void pump_load(void);
static void file_complete(void *unused);
#define RPC ((int(*)(void*,int,int,void*,int,void*,int,void*,void*))0x11f0b0)
#define BIND ((int(*)(void*,int,int))0x11eed0)
#define FLUSH ((void(*)(int))0x11b260)
#define DMA ((int(*)(void*,int))0x11df08)
#define DMASTAT ((int(*)(int))0x11b380)
static int call(int cmd,void *data,int n){FLUSH(0);int e=RPC(client,cmd,0,data,n,reply,64,0,0);telemetry[9]=e;for(int i=0;i<7;i++)telemetry[16+i]=reply[i];for(int i=0;i<9;i++)iopstats[i]=reply[7+i];return e;}
static int native_guard;
void player_stop(void){
 wanted=0;
 /* A read still in flight completes into io_reply and is ignored. */
 if(load_stage){load_stage=0;close_pending=1;}
 if(ready)call(4,0,0);
 if(opened){ov_clear(&vf);opened=0;}fill=0;telemetry[1]=0;telemetry[5]++;
}
void player_start(int paused){
 telemetry[6]++;telemetry[7]=*(volatile unsigned char*)0x5dbb98;
 if(paused||telemetry[7]>=101)return;
 NATIVE(0x20,0);
 load_track=telemetry[7];load_stage=1;wanted=1;close_pending=0;telemetry[1]=2;
 telemetry[8]=telemetry[9]=telemetry[30]=0;telemetry[25]=0;
}
int player_native(unsigned command){
 if(native_guard||(command&0x7fff)||*(volatile unsigned char*)0x5dbb98>=101)return 0;
 native_guard=1;player_stop();player_start(0);native_guard=0;return 1;
}
static void fallback(unsigned reason){
 player_stop();telemetry[30]=reason;telemetry[31]++;
 int guard=native_guard;native_guard=1;NATIVE(0,0);native_guard=guard;
}
static unsigned crc32(const void *data,unsigned n){
 crc_init();
 unsigned c=~0u;const unsigned char *p=data;for(unsigned i=0;i<n;i++)c=crc_table[(c^p[i])&255]^(c>>8);return ~c;
}
static void file_complete(void *unused){(void)unused;file_pending=0;}
static int queue_file(int cmd,unsigned off,unsigned len){
 file_args[0]=off;file_args[1]=len;io_reply[0]=0;file_pending=1;FLUSH(0);
 int e=RPC(file_client,cmd,1,file_args,cmd==11?8:0,io_reply,sizeof(io_reply),(void*)file_complete,0);
 if(e<0){file_pending=0;telemetry[9]=e;return -1;}return 0;
}
static int file_result(void){return io_reply[0]==0x46494c31?(int)io_reply[1]:-1;}
static unsigned *entry(void){return (unsigned*)(metadata+2048+load_track*64);}
static int select_entry(void){
 unsigned *h=(unsigned*)metadata,*a=entry();
 if(a[0]!=load_track||a[1]!=1)return 4;
 if(a[2]<18432||a[2]%2048||!a[3]||a[3]>SONG_MAX||a[2]>h[8]||a[3]>h[8]-a[2]||a[4]!=48000||a[5]!=2||!a[6]||(h[2]==1?(a[7]!=0||a[8]!=a[6]||a[9]>0x7fff):(a[7]>=a[8]||a[8]>a[6]||a[9]>260904||a[11]>1)))return 5;
 for(int i=h[2]==1?11:12;i<16;i++)if(a[i])return 5;
 song_frames=a[6];song_loop_start=a[7];song_loop_end=a[8];song_once=h[2]==2?a[11]:0;song_gain=h[2]==2?a[9]:65536;requested_volume=h[2]==1?a[9]:0x4800;
 stream_reset(a[3]);
 return 0;
}
static void pump_load(void){
 if(load_stage==1){
  if(metadata_valid){int e=select_entry();if(e){load_stage=0;fallback(e);return;}}
  if(queue_file(10,0,0)<0){fallback(2);return;}load_stage=2;return;
 }
 if(load_stage==2){
  if(file_result()!=0x20000000){fallback(2);return;}
  if(metadata_valid){load_stage=3;}
  else{if(queue_file(11,0,sizeof(metadata))<0){fallback(2);return;}load_stage=6;return;}
 }
 if(load_stage==6){
  if(file_result()!=sizeof(metadata)){fallback(2);return;}memcpy(metadata,io_reply+16,sizeof(metadata));
  unsigned *h=(unsigned*)metadata;
  if(memcmp(metadata,"SRWZVOC1",8)||(h[2]!=1&&h[2]!=2)||h[3]!=2048||h[4]!=2048||h[5]!=64||h[6]!=256||h[7]!=18432||h[8]<18432||h[8]>0x20000000||h[9]!=0x20000000||h[10]!=(h[2]==1?0x53500001:0x53500002)){fallback(3);return;}
  unsigned hc=h[12];h[12]=0;int valid=crc32(metadata,2048)==hc&&crc32(metadata+2048,16384)==h[11];h[12]=hc;if(!valid){fallback(3);return;}
  metadata_valid=1;int e=select_entry();if(e){fallback(e);return;}load_stage=3;
 }
 if(load_stage==4){
  if(file_result()!=(int)load_count){fallback(2);return;}
  int e=stream_feed(load_at,(unsigned char*)(io_reply+16),load_count,entry()[10]);
  if(e){fallback(e);return;}
  telemetry[28]=crc_pos+(tail_pos-tail_off);telemetry[29]=song_size;
  load_stage=3;
 }
 if(load_stage==3){
  if(!stream_next(&load_at,&load_count))return;
  if(queue_file(11,entry()[2]+load_at,load_count)<0){fallback(2);return;}load_stage=4;return;
 }
}
static int init(void){
 telemetry[1]=2;unsigned size=(irx_end-irx_start+63)&~63;void *p=((void*(*)(int,int,int))0x123510)(0,size,0);telemetry[2]=(unsigned)p;if(!p)return -1;
 struct {void *src,*dest;int size,attr;} d={irx_start,p,size,0};FLUSH(0);int id=DMA(&d,1);while(DMASTAT(id)>=0){}int modret=0;int m=((int(*)(void*,int,void*,int*))0x123b30)(p,0,0,&modret);telemetry[3]=m;telemetry[4]=modret;((int(*)(void*))0x123590)(p);if(m<0)return -2;
 for(int i=0;i<20&&!client[9];i++)BIND(client,0x564f5242,0);if(!client[9])return -3;for(int i=0;i<20&&!file_client[9];i++)BIND(file_client,0x564f5243,0);if(!file_client[9])return -3;ready=1;return 0;
}
/* Decode one 8 KiB packet and queue it. Returns 1 when queued, 0 when waiting
 * for more of the song, -1 after a fallback. */
static int decode_step(void){
 int r=decode_pcm();if(r<0){fallback(-r);return -1;}if(!r)return 0;
 if(song_gain!=65536)for(int k=0;k<4096;k++){int v=((int64_t)pcm[k]*song_gain)>>16;pcm[k]=v>32767?32767:v< -32768?-32768:v;}
 for(int b=0;b<8;b++)for(int j=0;j<256;j++){packet[b*512+j]=pcm[(b*256+j)*2];packet[b*512+256+j]=pcm[(b*256+j)*2+1];}
 fill=0;call(2,packet,8192);if(song_finished)call(6,0,0);
 return 1;
}
/* IOP draining replies include preserved PCM and the current DMA grace period.
 * A native transfer can suspend a one-shot too: keep retrying until it drains. */
static void pump_drain(void){
 telemetry[1]=4;
 if(reply[1]==0)player_stop();
 else if(!reply[2])call(3,0,0);
}
void player_pump(void){
 telemetry[12]++;
 if(wanted&&!ready){int e=init();if(e<0){fallback(1);return;}}
 if(ready&&!file_pending){
  if(close_pending){close_pending=0;queue_file(12,0,0);}
  else if(load_stage)pump_load();
 }
 if(!wanted)return;
 if(!opened){
  if(load_stage!=3&&load_stage!=4)return;
  int e=stream_open();
  if(e<0){fallback(-e);return;}
  if(!e)return;
  call(5,&requested_volume,4);song_finished=0;fill=0;call(1,0,0);telemetry[13]=0;telemetry[15]=2166136261u;telemetry[1]=1;
 }
 call(0,0,0);if(song_finished){pump_drain();return;}int budget=1;
 /* Keep the IOP ring 2 blocks short of the capacity it reports. */
 unsigned cap=(reply[0]>>8)==0x50434d?reply[0]&0xff:14;
 while(reply[1]<cap-2 && budget-- && !song_finished){if(decode_step()<0)return;}
 if(!reply[2])call(3,0,0);telemetry[1]=3;
}
