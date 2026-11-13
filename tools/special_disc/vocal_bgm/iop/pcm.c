/* PCM sink for the VOCAL.BIN player. DMA 1 is home; DMA 0 is a temporary shelter
 * shared with native speech. AutoDMA runs without resetting libsd or touching
 * voice master volumes. Buffers are 512-byte L/R blocks.
 *
 * v3: the game also uploads per-attack sound effects to SPU2 RAM through core 1
 * (sceSdVoiceTrans channel 1). While our AutoDMA owned that channel those uploads
 * failed and battles played stale samples. The native modules' libsd import stubs
 * are redirected to wrappers that stop our AutoDMA before any native core-1
 * transfer; the EE restarts it (command 3) once the channel is free again.
 * Disc reads run on their own RPC server thread so PCM requests never wait
 * behind a CD read. SP menus stop calling the audio update for ~0.6 s, which
 * emptied the old 16-block ring, so v3 used 20 blocks (~0.85 s). The IOP in
 * Original/Best has no room to spare (a 32-block ring crashed battle loading), so
 * the file buffer shrank from 64 to 32 KiB to keep the v2 footprint.
 *
 * v4: the game's own IOP loader reads each battle's sound-effect bank with
 * sceCdRead and does not retry. A VOCAL.BIN read in flight made those reads fail,
 * so a stale buffer was uploaded and that bank stayed silent. Native sceCdRead
 * stubs now go through a wrapper that waits for our read to finish, and our reads
 * start only while the drive is idle (sceCdSync) and no native read is being
 * issued.
 *
 * v5: a battle uploads sound-effect banks in bursts of 32 KiB pieces on core 1
 * when the attacking side changes. Stopping for every piece chopped the music
 * and dropped the audio already queued in the transfer buffer. The stream now
 * moves to the other core's block transfer when the game needs the one it is on
 * (core 0 carries only one speech upload per line, at other moments), keeps the
 * unplayed part of the buffer across the move, and returns to core 1 once that
 * channel has been quiet for a while. Busy channels or a failed start defer
 * playback until the EE retries, including during one-shot draining.
 * The ring lost one block to pay for the 8 KiB scratch buffer. */
#include <irx.h>
#include <thbase.h>
#include <thsemap.h>
#include <intrman.h>
#include <sifrpc.h>
#include <libsd.h>
#include <sysclib.h>
#include <ioman.h>
#include <loadcore.h>
#include <sysmem.h>
#include <cdvdman.h>
IRX_ID("vocalpcm",1,5);
#define BLOCK 8192
#define N 19
#define FILE_CHUNK 32768
static unsigned char dma[BLOCK*2] __attribute__((aligned(64)));
static unsigned char ring[N][BLOCK] __attribute__((aligned(64)));
static unsigned char rpcbuf[BLOCK] __attribute__((aligned(64)));
static unsigned char filebuf[64] __attribute__((aligned(64)));
static SifRpcDataQueue_t queue,file_queue;
static SifRpcServerData_t server,file_server;
static unsigned char scratch[BLOCK] __attribute__((aligned(64)));
static volatile unsigned wr,rd,active,underruns,interrupts,draining;
/* cur: core carrying the stream while active. pend: unplayed bytes kept at the
 * front of dma while stopped. rd_off: bytes already taken from ring[rd%N].
 * fresh: the half of dma that holds data not played yet. */
static volatile unsigned cur,pend,rd_off,last_native1;
/* Once the ring empties, allow both DMA halves and one silent half for SPU2
 * input-buffer latency. Restart this grace period after every successful move:
 * interrupt counts from the old transfer cannot drain the new one. */
static volatile unsigned drain_wait;
static volatile int fresh;
/* Native use per core: a voice transfer in DMA mode still running, a call in
 * progress, or a native block transfer that owns the channel until stopped. */
static volatile unsigned native_voice[2],native_block[2],native_io[2];
static int sema;
static int music_fd=-1;
static unsigned file_result[(FILE_CHUNK+64)/4] __attribute__((aligned(64)));
static unsigned volume=0x4800;
static sceSdTransIntrHandler previous[2];
static void *previous_arg[2];
static unsigned saved_vol[2][2];
static unsigned result[16] __attribute__((aligned(64)));
/* [0..2] stubs patched (voice, block, handler); [3] native ch1 voice transfers;
 * [4] deferred native handoffs; [5] native block transfers on core 1 (low 16
 * bits) and core 0 (high 16 bits); [6] sceCdRead stubs patched (high 16 bits) and
 * native reads that waited for ours (low 16 bits); [7] our reads that waited for
 * the drive (low 16 bits) and moves between cores (high 16 bits);
 * [8] largest free IOP block once loaded. */
static volatile unsigned stats[9];
/* Disc arbitration: cd_ours while one of our file operations runs, cd_native
 * while a native sceCdRead is being issued. Both change with interrupts off. */
static volatile unsigned cd_ours,cd_native;
static int wrap_cdread(u32 lsn,u32 sectors,void *buf,sceCdRMode *mode){
 int s,waited=0;
 if(!QueryIntrContext()){
  for(int i=0;i<4000;i++){
   CpuSuspendIntr(&s);
   if(!cd_ours){cd_native++;CpuResumeIntr(s);int r=sceCdRead(lsn,sectors,buf,mode);CpuSuspendIntr(&s);cd_native--;CpuResumeIntr(s);return r;}
   CpuResumeIntr(s);
   if(!waited){waited=1;stats[6]++;}
   DelayThread(500);
  }
 }
 return sceCdRead(lsn,sectors,buf,mode);
}
/* Take the drive for one of our file operations. The drive must have been idle
 * for QUIET consecutive polls (about 1 ms each) with no native read being issued:
 * during a battle load the game reads almost continuously, and slipping a read
 * of ours between two of its reads costs it two long seeks. Gives up after ~3 s
 * so music cannot hang forever; the wrapped loader still waits for us then. */
#define QUIET 60
static void cd_take(void){
 int s,waited=0,idle=0;
 for(int i=0;i<3000;i++){
  CpuSuspendIntr(&s);
  if(!cd_native&&sceCdSync(1)==0){if(++idle>=QUIET){cd_ours=1;CpuResumeIntr(s);return;}}
  else{idle=0;if(!waited){waited=1;stats[7]++;}}
  CpuResumeIntr(s);
  DelayThread(1000);
 }
 cd_ours=1;
}

static unsigned now(void){iop_sys_clock_t c;GetSystemTime(&c);return (c.hi<<24)|(c.lo>>8);}
/* 150 ms in now() units (256 system-clock ticks, 6.94 us). */
#define HOME_QUIET 21600
static int intr(int ch,void *arg){
 (void)arg;
 if(active&&(unsigned)ch==cur){
  interrupts++;
  if(draining&&wr==rd&&drain_wait)drain_wait--;
  iSignalSema(sema);
 }
 return 1;
}
static unsigned avail(void){return pend+(wr-rd)*BLOCK-rd_off;}
/* Callers hold interrupts suspended. */
static void take(unsigned char *dst,unsigned n){
 while(n){
  if(wr==rd){memset(dst,0,n);if(!draining)underruns++;return;}
  unsigned k=BLOCK-rd_off;if(k>n)k=n;
  drain_wait=3;
  memcpy(dst,ring[rd%N]+rd_off,k);dst+=k;n-=k;rd_off+=k;
  if(rd_off==BLOCK){rd_off=0;rd++;}
 }
}
/* Refill the half that is not playing, once per half: a signal left over from
 * before a move must not overwrite data that has not been played. */
static void refill(void){
 if(active){int half=1-((sceSdBlockTransStatus(cur,0)>>24)&1);if(half!=fresh){take(dma+half*BLOCK,BLOCK);fresh=half;}}
}
static void worker(void *arg){
 (void)arg;int s;
 for(;;){
  WaitSema(sema);CpuSuspendIntr(&s);
  refill();
  CpuResumeIntr(s);
 }
}

/* Callers hold interrupts suspended. keep: move what has not been played to the
 * front of dma so the next start continues from there. */
static void adma_halt(int keep){
 if(!keep){pend=drain_wait=0;fresh=-1;}
 if(!active)return;
 unsigned c=cur,st=sceSdBlockTransStatus(c,0);
 active=0;sceSdSetParam(0xf80|c,saved_vol[c][0]);sceSdSetParam(0x1080|c,saved_vol[c][1]);
 sceSdBlockTrans(c,SD_TRANS_STOP,0,0);sceSdSetTransIntrHandler(c,previous[c],previous_arg[c]);
 pend=0;
 if(!keep)return;
 unsigned half=(st>>24)&1,off=((st&0xffffff)-(((unsigned)dma+half*BLOCK)&0xffffff))&0xffffff;
 if(off>BLOCK)off=BLOCK;
 off&=~1023u;
 unsigned n=BLOCK-off;
 if(half==0){
  memmove(dma,dma+off,n);
  if(fresh==1){memmove(dma+n,dma+BLOCK,BLOCK);n+=BLOCK;}
 }else{
  memcpy(scratch,dma+BLOCK+off,n);
  if(fresh==0){memmove(dma+n,dma,BLOCK);memcpy(dma,scratch,n);n+=BLOCK;}
  else memcpy(dma,scratch,n);
 }
 pend=n;
}
static int adma_start(unsigned c){
 unsigned bytes=avail();
 if(active||!bytes||(!draining&&bytes<2*BLOCK))return 0;
 /* Keep the prepared buffer pending until libsd accepts it. A failed start
  * must neither lose these bytes nor consume the ring a second time. */
 take(dma+pend,2*BLOCK-pend);pend=2*BLOCK;
 saved_vol[c][0]=sceSdGetParam(0xf80|c);saved_vol[c][1]=sceSdGetParam(0x1080|c);
 previous_arg[c]=sceSdGetTransIntrHandlerArgument(c);previous[c]=sceSdSetTransIntrHandler(c,intr,0);
 if(sceSdBlockTrans(c,0x10,dma,sizeof(dma))<0){
  sceSdSetTransIntrHandler(c,previous[c],previous_arg[c]);return 0;
 }
 pend=0;fresh=1;cur=c;drain_wait=3;active=1;
 sceSdSetParam(0xf80|c,volume);sceSdSetParam(0x1080|c,volume);
 return 1;
}
static int channel_free(unsigned c){
 if(native_voice[c]&&sceSdVoiceTransStatus(c,0)==1)native_voice[c]=0;
 return !native_voice[c]&&!native_block[c]&&!native_io[c];
}
/* The game is about to use core c's channel: move the stream to the other core,
 * or stop if that one is busy too. */
static void yield(unsigned c){
 if(c==1)last_native1=now();
 if(!active||cur!=c)return;
 adma_halt(1);
 if(channel_free(1-c)&&adma_start(1-c))stats[7]+=0x10000;else stats[4]++;
}

static int wrap_voice(s16 ch,u16 mode,u8 *iop,u32 *spu,u32 size){
 int s;unsigned c=ch&1;
 CpuSuspendIntr(&s);yield(c);if(c)stats[3]++;
 native_io[c]++;
 CpuResumeIntr(s);
 /* Keep the channel marked busy until the call returns, so a PCM start cannot
  * slip in before the transfer starts (DMA mode) or while the CPU is still
  * writing it (IO mode). A DMA transfer then stays busy until
  * sceSdVoiceTransStatus reports completion. */
 int r=sceSdVoiceTrans(ch,mode,iop,spu,size);
 CpuSuspendIntr(&s);native_io[c]--;
 if(r>=0){if((mode&3)==SD_TRANS_STOP)native_voice[c]=0;else if(!(mode&SD_TRANS_MODE_IO))native_voice[c]=1;}
 if(c)last_native1=now();CpuResumeIntr(s);
 return r;
}
static int wrap_block(s16 ch,u16 mode,u8 *iop,u32 size,u32 extra){
 int s;unsigned c=ch&1;
 CpuSuspendIntr(&s);stats[5]+=c?1:0x10000;
 /* A native stop for a block transfer it never started would stop our PCM. */
 if((mode&3)==SD_TRANS_STOP&&!native_block[c]&&active&&cur==c){CpuResumeIntr(s);return 0;}
 if((mode&3)!=SD_TRANS_STOP)yield(c);
 /* STOP still owns the channel until the real call has returned. */
 native_io[c]++;
 CpuResumeIntr(s);
 int r=sceSdBlockTrans(ch,mode,iop,size,extra);
 CpuSuspendIntr(&s);native_io[c]--;
 if(r>=0)native_block[c]=(mode&3)!=SD_TRANS_STOP;
 if(c)last_native1=now();CpuResumeIntr(s);
 return r;
}
static sceSdTransIntrHandler wrap_handler(int ch,sceSdTransIntrHandler func,void *arg){
 int s;
 if(ch==0||ch==1){
  /* While our AutoDMA runs on this core, record the native handler for
   * restoration instead of letting it replace ours. */
  CpuSuspendIntr(&s);
  if(active&&cur==(unsigned)ch){sceSdTransIntrHandler old=previous[ch];previous[ch]=func;previous_arg[ch]=arg;CpuResumeIntr(s);return old;}
  sceSdTransIntrHandler old=sceSdSetTransIntrHandler(ch,func,arg);
  CpuResumeIntr(s);return old;
 }
 return sceSdSetTransIntrHandler(ch,func,arg);
}

/* Redirect every other module's resolved libsd stub (j target; addiu $0,$0,id). */
static unsigned redirect(void *ours,unsigned id,void *wrapper){
 unsigned *own=ours,jump=*own,n=0;
 if(jump>>26!=2)return 0;
 for(unsigned *p=(unsigned*)0x1000;p<(unsigned*)0x1ffff8;p++)
  if(*p==jump&&p[1]==(0x24000000|id)&&p!=own){*p=0x08000000|(((unsigned)wrapper>>2)&0x3ffffff);n++;}
 return n;
}

static void *file_dispatch(int cmd,void *buf,int len){
 memset(file_result,0,64);file_result[0]=0x46494c31;int n=-1;
 if(cmd==10||cmd==11)cd_take();
 if(cmd==10){if(music_fd>=0)close(music_fd);music_fd=open("cdrom0:\\BGM\\VOCAL.BIN;1",1);if(music_fd>=0)n=lseek(music_fd,0,2);}
 if(cmd==11 && music_fd>=0 && len==8){unsigned *a=buf;if(a[1]<=FILE_CHUNK && a[0]<0x20000000 && a[1]<=0x20000000-a[0] && lseek(music_fd,a[0],0)==(int)a[0])n=read(music_fd,file_result+16,a[1]);}
 if(cmd==12){if(music_fd>=0)close(music_fd);music_fd=-1;n=0;}
 cd_ours=0;file_result[1]=n;return file_result;
}
static void *dispatch(int cmd,void *buf,int len){
 int s;
 if(cmd==6){CpuSuspendIntr(&s);draining=1;drain_wait=3;CpuResumeIntr(s);}
 if(cmd==5 && len==4 && *(unsigned*)buf<=0x7fff)volume=*(unsigned*)buf;
 /* A new song only stops our own transfer; a native transfer may be running. */
 if(cmd==1||cmd==4){
  CpuSuspendIntr(&s);adma_halt(0);wr=rd=rd_off=pend=draining=drain_wait=0;fresh=-1;
  if(cmd==1){underruns=interrupts=0;memset(dma,0,sizeof(dma));}
  CpuResumeIntr(s);
 }
 if(cmd==2 && len==BLOCK && wr-rd<N){memcpy(ring[wr%N],buf,BLOCK);wr++;}
 if(cmd==3){CpuSuspendIntr(&s);if(!active){if(channel_free(1))adma_start(1);else if(channel_free(0))adma_start(0);}CpuResumeIntr(s);}
 /* Core 0 is only a shelter: go back once core 1 has been quiet for a while. */
 CpuSuspendIntr(&s);
 if(active&&cur==0&&channel_free(1)&&now()-last_native1>HOME_QUIET){adma_halt(1);if(adma_start(1))stats[7]+=0x10000;}
 result[0]=0x50434d00|N;result[1]=wr-rd;result[2]=active;result[3]=underruns;result[4]=interrupts;result[5]=wr;result[6]=rd;
 /* During draining, zero means the ring, preserved bytes and DMA grace period
  * have all drained. Normal replies retain the ring-slot count used for flow control. */
 if(draining)result[1]+=(pend+BLOCK-1)/BLOCK+(active&&drain_wait?1:0);
 for(int i=0;i<9;i++)result[7+i]=stats[i];
 CpuResumeIntr(s);
 return result;
}
static void rpc(void *arg){(void)arg;sceSifInitRpc(0);sceSifSetRpcQueue(&queue,GetThreadId());sceSifRegisterRpc(&server,0x564f5242,dispatch,rpcbuf,0,0,&queue);sceSifRpcLoop(&queue);}
static void file_rpc(void *arg){(void)arg;sceSifInitRpc(0);sceSifSetRpcQueue(&file_queue,GetThreadId());sceSifRegisterRpc(&file_server,0x564f5243,file_dispatch,filebuf,0,0,&file_queue);sceSifRpcLoop(&file_queue);}
int _start(int argc,char **argv){
 (void)argc;(void)argv;int s;
 stats[8]=QueryMaxFreeMemSize();
 CpuSuspendIntr(&s);
 stats[0]=redirect((void*)sceSdVoiceTrans,17,(void*)wrap_voice);
 stats[1]=redirect((void*)sceSdBlockTrans,18,(void*)wrap_block);
 stats[2]=redirect((void*)sceSdSetTransIntrHandler,26,(void*)wrap_handler);
 stats[6]=redirect((void*)sceCdRead,6,(void*)wrap_cdread)<<16;
 FlushIcache();CpuResumeIntr(s);
 iop_sema_t sm={0};sm.initial=0;sm.max=4;sema=CreateSema(&sm);
 iop_thread_t t={0};t.attr=TH_C;t.thread=worker;t.priority=35;t.stacksize=2048;int id=CreateThread(&t);StartThread(id,0);
 t.thread=rpc;t.priority=45;id=CreateThread(&t);StartThread(id,0);
 t.thread=file_rpc;t.priority=50;id=CreateThread(&t);StartThread(id,0);
 return 0;
}
