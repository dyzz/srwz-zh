/* PCM sink for the VOCAL.BIN player. DMA 0 is owned by native streamed speech.
 * DMA 1 feeds PCM through core 1 AutoDMA without resetting libsd or touching
 * voice master volumes. Buffers are 512-byte L/R blocks.
 *
 * v3: the game also uploads per-attack sound effects to SPU2 RAM through core 1
 * (sceSdVoiceTrans channel 1). While our AutoDMA owned that channel those uploads
 * failed and battles played stale samples. The native modules' libsd import stubs
 * are redirected to wrappers that stop our AutoDMA before any native core-1
 * transfer; the EE restarts it (command 3) once the channel is free again.
 * Disc reads run on their own RPC server thread so PCM requests never wait
 * behind a CD read. SP menus stop calling the audio update for ~0.6 s, which
 * emptied the old 16-block ring, so it now has 20 blocks (~0.85 s). The IOP in
 * Original/Best has no room to spare (a 32-block ring crashed battle loading), so
 * the file buffer shrank from 64 to 32 KiB to keep the v2 footprint. */
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
IRX_ID("vocalpcm",1,3);
#define BLOCK 8192
#define N 20
#define FILE_CHUNK 32768
static unsigned char dma[BLOCK*2] __attribute__((aligned(64)));
static unsigned char ring[N][BLOCK] __attribute__((aligned(64)));
static unsigned char rpcbuf[BLOCK] __attribute__((aligned(64)));
static unsigned char filebuf[64] __attribute__((aligned(64)));
static SifRpcDataQueue_t queue,file_queue;
static SifRpcServerData_t server,file_server;
static volatile unsigned wr,rd,active,underruns,interrupts,draining;
/* Native core-1 use: a voice transfer in DMA mode still running, or a native
 * block transfer that owns the channel until it is stopped. */
static volatile unsigned native_voice,native_block,native_io;
static int sema;
static int music_fd=-1;
static unsigned file_result[(FILE_CHUNK+64)/4] __attribute__((aligned(64)));
static unsigned volume=0x4800;
static sceSdTransIntrHandler previous;
static void *previous_arg;
static unsigned result[16] __attribute__((aligned(64)));
/* [0..2] stubs patched (voice, block, handler); [3] native ch1 voice transfers;
 * [4] pauses; [5] native ch1 block transfers; [6] native ch1 handler changes;
 * [7] last ch1 voice mode; [8] largest free IOP block once loaded. */
static volatile unsigned stats[9];

static int intr(int ch,void *arg){(void)ch;(void)arg;interrupts++;iSignalSema(sema);return 1;}
static void worker(void *arg){(void)arg;for(;;){WaitSema(sema);if(!active)continue;unsigned half=1-((sceSdBlockTransStatus(1,0)>>24)&1);if(wr!=rd){memcpy(dma+half*BLOCK,ring[rd%N],BLOCK);rd++;}else{memset(dma+half*BLOCK,0,BLOCK);if(!draining)underruns++;}}}

/* Callers hold interrupts suspended. */
static void adma_stop(void){
 if(!active)return;
 active=0;sceSdSetParam(0xf81,0);sceSdSetParam(0x1081,0);sceSdBlockTrans(1,SD_TRANS_STOP,0,0);sceSdSetTransIntrHandler(1,previous,previous_arg);
}
static int channel_free(void){
 if(native_voice&&sceSdVoiceTransStatus(1,0)==1)native_voice=0;
 return !native_voice&&!native_block&&!native_io;
}

static int wrap_voice(s16 ch,u16 mode,u8 *iop,u32 *spu,u32 size){
 int s;
 if((ch&1)==1){
  CpuSuspendIntr(&s);if(active){adma_stop();stats[4]++;}stats[3]++;stats[7]=mode;
  if((mode&3)!=SD_TRANS_STOP){if(mode&SD_TRANS_MODE_IO)native_io++;else native_voice=1;}
  CpuResumeIntr(s);
  /* An IO-mode transfer is written by the CPU in this call; keep the channel
   * marked busy until it returns so a PCM restart cannot preempt it. */
  if(!(mode&SD_TRANS_MODE_IO)||(mode&3)==SD_TRANS_STOP)return sceSdVoiceTrans(ch,mode,iop,spu,size);
  int r=sceSdVoiceTrans(ch,mode,iop,spu,size);
  CpuSuspendIntr(&s);native_io--;CpuResumeIntr(s);
  return r;
 }
 return sceSdVoiceTrans(ch,mode,iop,spu,size);
}
static int wrap_block(s16 ch,u16 mode,u8 *iop,u32 size,u32 extra){
 int s;
 if((ch&1)==1){
  CpuSuspendIntr(&s);stats[5]++;
  /* A native stop for a block transfer it never started would stop our PCM. */
  if((mode&3)==SD_TRANS_STOP&&!native_block&&active){CpuResumeIntr(s);return 0;}
  if((mode&3)==SD_TRANS_STOP)native_block=0;
  else{if(active){adma_stop();stats[4]++;}native_block=1;}
  CpuResumeIntr(s);
 }
 return sceSdBlockTrans(ch,mode,iop,size,extra);
}
static sceSdTransIntrHandler wrap_handler(int ch,sceSdTransIntrHandler func,void *arg){
 int s;
 if(ch==1){
  /* While our AutoDMA runs, record the native handler for restoration instead
   * of letting it replace ours. */
  CpuSuspendIntr(&s);stats[6]++;
  if(active){sceSdTransIntrHandler old=previous;previous=func;previous_arg=arg;CpuResumeIntr(s);return old;}
  CpuResumeIntr(s);
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
 if(cmd==10){if(music_fd>=0)close(music_fd);music_fd=open("cdrom0:\\BGM\\VOCAL.BIN;1",1);if(music_fd>=0)n=lseek(music_fd,0,2);}
 if(cmd==11 && music_fd>=0 && len==8){unsigned *a=buf;if(a[1]<=FILE_CHUNK && a[0]<0x20000000 && a[1]<=0x20000000-a[0] && lseek(music_fd,a[0],0)==(int)a[0])n=read(music_fd,file_result+16,a[1]);}
 if(cmd==12){if(music_fd>=0)close(music_fd);music_fd=-1;n=0;}
 file_result[1]=n;return file_result;
}
static void *dispatch(int cmd,void *buf,int len){
 int s;
 if(cmd==6)draining=1;
 if(cmd==5 && len==4 && *(unsigned*)buf<=0x7fff)volume=*(unsigned*)buf;
 /* A new song only stops our own transfer; a native core-1 transfer may be running. */
 if(cmd==1){CpuSuspendIntr(&s);adma_stop();wr=rd=underruns=interrupts=draining=0;memset(dma,0,sizeof(dma));CpuResumeIntr(s);}
 if(cmd==2 && len==BLOCK && wr-rd<N){memcpy(ring[wr%N],buf,BLOCK);wr++;}
 if(cmd==3){CpuSuspendIntr(&s);if(!active && wr-rd>=2 && channel_free()){memcpy(dma,ring[rd++%N],BLOCK);memcpy(dma+BLOCK,ring[rd++%N],BLOCK);previous_arg=sceSdGetTransIntrHandlerArgument(1);previous=sceSdSetTransIntrHandler(1,intr,0);active=1;sceSdBlockTrans(1,0x10,dma,sizeof(dma));sceSdSetParam(0xf81,volume);sceSdSetParam(0x1081,volume);}CpuResumeIntr(s);}
 if(cmd==4){CpuSuspendIntr(&s);adma_stop();CpuResumeIntr(s);}
 result[0]=0x50434d00|N;result[1]=wr-rd;result[2]=active;result[3]=underruns;result[4]=interrupts;result[5]=wr;result[6]=rd;
 for(int i=0;i<9;i++)result[7+i]=stats[i];
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
 FlushIcache();CpuResumeIntr(s);
 iop_sema_t sm={0};sm.initial=0;sm.max=4;sema=CreateSema(&sm);
 iop_thread_t t={0};t.attr=TH_C;t.thread=worker;t.priority=35;t.stacksize=2048;int id=CreateThread(&t);StartThread(id,0);
 t.thread=rpc;t.priority=45;id=CreateThread(&t);StartThread(id,0);
 t.thread=file_rpc;t.priority=50;id=CreateThread(&t);StartThread(id,0);
 return 0;
}
