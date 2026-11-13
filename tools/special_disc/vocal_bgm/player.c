/* SP address template, relocated for Z/Best. Vorbis is loaded asynchronously.
 * Native Sony SIF entry points below require the asserted SLPS_259.20 preimages.
 * telemetry[27] is a test-only seek request; [28:29] show bytes loaded/total
 * during loading, then report the test seek result when requested.
 * No host audio or runtime file is used by the player.
 *
 * v3 starts playback before the song is fully loaded: the last 64 KiB (which
 * Tremor scans when opening) and the first 64 KiB are read first, decoding
 * starts, and the rest of the head streams in behind the decoder on the IOP's
 * separate file server. After the decoder opens, further chunks are read only to
 * keep LOOKAHEAD bytes ahead of it, so a battle start does not compete with the
 * game's own disc reads. A custom loop range or a pending seek reads the rest at
 * once; seeks wait for the complete song. The body CRC is checked once the last
 * chunk arrives. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "ivorbisfile.h"
extern unsigned char irx_start[],irx_end[];
#define SONG_MAX (4*1024*1024)
#define FILE_CHUNK 32768
#define TAIL_BYTES 65536
#define HEAD_START 65536
#define READ_MARGIN 16384
#define LOOKAHEAD (128*1024)
static unsigned char song_start[SONG_MAX] __attribute__((aligned(64)));
static unsigned song_size, song_frames, song_loop_start, song_loop_end, song_once, song_gain, song_finished;
static unsigned char metadata[18432] __attribute__((aligned(64)));
static unsigned io_reply[(FILE_CHUNK+64)/4] __attribute__((aligned(64)));
volatile uint32_t telemetry[32]={0x564f5231};
/* IOP-side counters (see iop/pcm.c), refreshed by every PCM request. */
volatile uint32_t iopstats[9];
static OggVorbis_File vf;
static size_t source_pos;
static unsigned client[16] __attribute__((aligned(64)));
static unsigned reply[16] __attribute__((aligned(64)));
static short pcm[4096] __attribute__((aligned(64)));
static short packet[4096] __attribute__((aligned(64)));
static int opened,ready,wanted,starved,fill,seek_wait;
/* Disk RPCs use their own client, IOP server thread and persistent buffers. The
 * completion ISR only clears a flag; nothing waits for CD on the EE. */
static unsigned file_client[16] __attribute__((aligned(64)));
static unsigned file_args[2] __attribute__((aligned(64)));
static volatile int file_pending;
static int load_stage,close_pending,metadata_valid;
static unsigned load_track,load_at,load_count,load_crc,cached_track=~0u;
/* The song is read as [tail_off,size) first, then [0,tail_off). */
static unsigned tail_off,tail_pos,head_pos,open_head;
static int tail_done,loaded_all;
static unsigned requested_volume;

static unsigned crc_table[256];
static int crc_ready;
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
static size_t available(size_t pos){
 if(pos>=song_size)return 0;
 if(loaded_all)return song_size-pos;
 if(pos<head_pos)return head_pos-pos;
 if(tail_done&&pos>=tail_off)return song_size-pos;
 return 0;
}
static size_t rd(void *p,size_t s,size_t n,void *unused){
 if(!s)return 0;size_t left=available(source_pos);
 if(left<n*s&&source_pos+left<song_size)starved=1;
 if(n>left/s)n=left/s;memcpy(p,song_start+source_pos,n*s);source_pos+=n*s;return n;
}
static int sk(void *unused,ogg_int64_t off,int whence){ogg_int64_t x=(whence==0?0:whence==1?source_pos:song_size)+off;if(x<0||x>song_size)return -1;source_pos=x;return 0;}
static long tl(void *unused){return source_pos;}
void arena_reset(void);
static int open_song(void){source_pos=0;starved=0;arena_reset();ov_callbacks cb={rd,sk,0,tl};int e=ov_open_callbacks((void*)1,&vf,0,0,cb);telemetry[8]=e;if(e<0)return e;opened=1;vorbis_info *vi=ov_info(&vf,-1);telemetry[10]=vi->rate;telemetry[11]=vi->channels;return vi->rate==48000&&vi->channels==2&&ov_streams(&vf)==1&&ov_pcm_total(&vf,-1)==song_frames?0:-100;}
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
 load_track=telemetry[7];load_stage=1;wanted=1;close_pending=0;seek_wait=0;loaded_all=tail_done=0;head_pos=tail_off=open_head=0;telemetry[1]=2;
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
 if(!crc_ready){for(unsigned i=0;i<256;i++){unsigned c=i;for(int j=0;j<8;j++)c=(c>>1)^((0-(c&1))&0xedb88320u);crc_table[i]=c;}crc_ready=1;}
 unsigned c=~0u;const unsigned char *p=data;for(unsigned i=0;i<n;i++)c=crc_table[(c^p[i])&255]^(c>>8);return ~c;
}
static void file_complete(void *unused){(void)unused;file_pending=0;}
static int queue_file(int cmd,unsigned off,unsigned len){
 file_args[0]=off;file_args[1]=len;io_reply[0]=0;file_pending=1;FLUSH(0);
 int e=RPC(file_client,cmd,1,file_args,cmd==11?8:0,io_reply,sizeof(io_reply),(void*)file_complete,0);
 if(e<0){file_pending=0;telemetry[9]=e;return -1;}return 0;
}
static int file_result(void){return io_reply[0]==0x46494c31?(int)io_reply[1]:-1;}
static unsigned crc_step(unsigned crc,const unsigned char *data,unsigned n){for(unsigned i=0;i<n;i++)crc=crc_table[(crc^data[i])&255]^(crc>>8);return crc;}
static int select_entry(void){
 unsigned *h=(unsigned*)metadata,*a=(unsigned*)(metadata+2048+load_track*64);
 if(a[0]!=load_track||a[1]!=1)return 4;
 if(a[2]<18432||a[2]%2048||!a[3]||a[3]>SONG_MAX||a[2]>h[8]||a[3]>h[8]-a[2]||a[4]!=48000||a[5]!=2||!a[6]||(h[2]==1?(a[7]!=0||a[8]!=a[6]||a[9]>0x7fff):(a[7]>=a[8]||a[8]>a[6]||a[9]>260904||a[11]>1)))return 5;
 for(int i=h[2]==1?11:12;i<16;i++)if(a[i])return 5;
 song_frames=a[6];song_loop_start=a[7];song_loop_end=a[8];song_once=h[2]==2?a[11]:0;song_gain=h[2]==2?a[9]:65536;song_size=a[3];requested_volume=h[2]==1?a[9]:0x4800;
 return 0;
}
static int next_chunk(void){
 unsigned *a=(unsigned*)(metadata+2048+load_track*64);
 if(!tail_done){load_at=tail_pos;load_count=song_size-tail_pos;}else{load_at=head_pos;load_count=tail_off-head_pos;}
 if(load_count>FILE_CHUNK)load_count=FILE_CHUNK;
 return queue_file(11,a[2]+load_at,load_count);
}
static int want_more(void){
 if(!tail_done||!opened||seek_wait||song_loop_end<song_frames)return 1;
 return head_pos<source_pos+LOOKAHEAD;
}
static void pump_load(void){
 if(load_stage==1){
  if(metadata_valid){int e=select_entry();if(e){load_stage=0;fallback(e);return;}
   if(cached_track==load_track){load_stage=0;loaded_all=tail_done=1;head_pos=tail_off=song_size;telemetry[28]=telemetry[29]=song_size;return;}}
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
  metadata_valid=1;load_stage=3;
 }
 if(load_stage==3){
  int e=select_entry();if(e){fallback(e);return;}
  cached_track=~0u;loaded_all=0;head_pos=0;open_head=0;load_crc=~0u;
  tail_off=song_size>2*TAIL_BYTES?((song_size-TAIL_BYTES)&~2047u):song_size;tail_pos=tail_off;tail_done=tail_off>=song_size;
  if(next_chunk()<0){fallback(2);return;}load_stage=4;return;
 }
 if(load_stage==4){
  if(file_result()!=(int)load_count){fallback(2);return;}
  memcpy(song_start+load_at,io_reply+16,load_count);
  if(!tail_done){tail_pos+=load_count;tail_done=tail_pos>=song_size;}
  else{load_crc=crc_step(load_crc,song_start+head_pos,load_count);head_pos+=load_count;}
  telemetry[28]=head_pos+(tail_done?song_size-tail_off:tail_pos-tail_off);telemetry[29]=song_size;
  if(head_pos<tail_off){if(!want_more()){load_stage=7;return;}if(next_chunk()<0)fallback(2);return;}
  unsigned *a=(unsigned*)(metadata+2048+load_track*64);
  load_crc=crc_step(load_crc,song_start+tail_off,song_size-tail_off);
  if((~load_crc)!=a[10]){fallback(6);return;}
  loaded_all=1;cached_track=load_track;
  if(queue_file(12,0,0)<0){fallback(2);return;}load_stage=5;return;
 }
 if(load_stage==7){if(want_more()){if(next_chunk()<0){fallback(2);return;}load_stage=4;}return;}
 if(load_stage==5)load_stage=0;
}
static int init(void){
 telemetry[1]=2;unsigned size=(irx_end-irx_start+63)&~63;void *p=((void*(*)(int,int,int))0x123510)(0,size,0);telemetry[2]=(unsigned)p;if(!p)return -1;
 struct {void *src,*dest;int size,attr;} d={irx_start,p,size,0};FLUSH(0);int id=DMA(&d,1);while(DMASTAT(id)>=0){}int modret=0;int m=((int(*)(void*,int,void*,int*))0x123b30)(p,0,0,&modret);telemetry[3]=m;telemetry[4]=modret;((int(*)(void*))0x123590)(p);if(m<0)return -2;
 for(int i=0;i<20&&!client[9];i++)BIND(client,0x564f5242,0);if(!client[9])return -3;for(int i=0;i<20&&!file_client[9];i++)BIND(file_client,0x564f5243,0);if(!file_client[9])return -3;ready=1;return 0;
}
/* Decode into pcm until one 8 KiB packet is queued. Returns 1 when queued, 0 when
 * waiting for more of the song, -1 after a fallback. A partial packet is kept. */
static int decode_step(void){
 int section=0;
 while(fill<8192){
  if(telemetry[13]>=song_loop_end){
   if(song_once){memset((char*)pcm+fill,0,8192-fill);fill=8192;song_finished=1;break;}
   if(!loaded_all){seek_wait=1;return 0;}
   telemetry[23]=telemetry[13];telemetry[24]=telemetry[15];telemetry[14]++;
   seek_wait=0;if(ov_pcm_seek(&vf,song_loop_start)<0){fallback(8);return -1;}telemetry[13]=song_loop_start;telemetry[15]=2166136261u;
  }
  if(!loaded_all&&source_pos<tail_off&&head_pos-source_pos<READ_MARGIN){telemetry[25]++;return 0;}
  unsigned limit=(song_loop_end-telemetry[13])*4;if(limit>(unsigned)(8192-fill))limit=8192-fill;
  starved=0;long n=ov_read(&vf,(char*)pcm+fill,limit,&section);
  if(n<=0){if(starved&&!loaded_all){telemetry[25]++;return 0;}telemetry[8]=n?n:-101;fallback(8);return -1;}
  for(long k=0;k<n;k++)telemetry[15]=(telemetry[15]^((unsigned char*)pcm)[fill+k])*16777619u;
  fill+=n;telemetry[13]+=n/4;telemetry[26]+=n/4;
 }
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
  if(load_stage==1||load_stage==2||load_stage==3||load_stage==6)return;
  unsigned need=tail_off<HEAD_START?tail_off:HEAD_START;
  if(!loaded_all&&(!tail_done||head_pos<need||head_pos<=open_head))return;
  open_head=head_pos;
  int e=open_song();
  if(e<0){
   /* Headers or the final page may need bytes not loaded yet: retry on the next chunk. */
   if(starved&&!loaded_all){if(opened){ov_clear(&vf);opened=0;}telemetry[25]++;return;}
   fallback(7);return;
  }
  call(5,&requested_volume,4);song_finished=0;fill=0;call(1,0,0);telemetry[13]=0;telemetry[15]=2166136261u;telemetry[1]=1;
 }
 if(telemetry[27]&&!loaded_all)seek_wait=1;
 if(telemetry[27]&&loaded_all){seek_wait=0;unsigned seek=telemetry[27];telemetry[27]=0;call(4,0,0);int e=ov_pcm_seek(&vf,(ogg_int64_t)seek*48000);telemetry[28]=seek;telemetry[29]=e;if(e<0){fallback(8);return;}fill=0;telemetry[13]=seek*48000;telemetry[15]=2166136261u;call(1,0,0);}
 call(0,0,0);if(song_finished){pump_drain();return;}int budget=1;
 /* Keep the IOP ring 2 blocks short of the capacity it reports. */
 unsigned cap=(reply[0]>>8)==0x50434d?reply[0]&0xff:14;
 while(reply[1]<cap-2 && budget-- && !song_finished){if(decode_step()<0)return;}
 if(!reply[2])call(3,0,0);telemetry[1]=3;
}
