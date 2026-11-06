/* SP proof-of-concept PCM sink. DMA 0 is owned by native streamed speech.
 * DMA 1 feeds PCM without resetting libsd or touching voice master volumes.
 * Buffers are 512-byte L/R blocks; restore the prior interrupt handler on stop. */
#include <irx.h>
#include <thbase.h>
#include <thsemap.h>
#include <intrman.h>
#include <sifrpc.h>
#include <libsd.h>
#include <sysclib.h>
#include <ioman.h>
IRX_ID("vocalpcm",1,1);
#define BLOCK 8192
#define N 16
static unsigned char dma[BLOCK*2] __attribute__((aligned(64)));
static unsigned char ring[N][BLOCK] __attribute__((aligned(64)));
static unsigned char rpcbuf[BLOCK] __attribute__((aligned(64)));
static SifRpcDataQueue_t queue;
static SifRpcServerData_t server;
static volatile unsigned wr,rd,active,underruns,interrupts,draining;
static int sema;
static int music_fd=-1;
static unsigned file_result[(65536+64)/4] __attribute__((aligned(64)));
static unsigned volume=0x4800;
static sceSdTransIntrHandler previous;
static void *previous_arg;
static unsigned result[16] __attribute__((aligned(64)));
static int intr(int ch,void *arg){(void)ch;(void)arg;interrupts++;iSignalSema(sema);return 1;}
static void worker(void *arg){(void)arg;for(;;){WaitSema(sema);if(!active)continue;unsigned half=1-((sceSdBlockTransStatus(1,0)>>24)&1);if(wr!=rd){memcpy(dma+half*BLOCK,ring[rd%N],BLOCK);rd++;}else{memset(dma+half*BLOCK,0,BLOCK);if(!draining)underruns++;}}}
static void *dispatch(int cmd,void *buf,int len){
 int s;
 if(cmd>=10 && cmd<=12){
  memset(file_result,0,64);file_result[0]=0x46494c31;int n=-1;
  if(cmd==10){if(music_fd>=0)close(music_fd);music_fd=open("cdrom0:\\BGM\\VOCAL.BIN;1",1);if(music_fd>=0)n=lseek(music_fd,0,2);}
  if(cmd==11 && music_fd>=0 && len==8){unsigned *a=buf;if(a[1]<=65536 && a[0]<0x20000000 && a[1]<=0x20000000-a[0] && lseek(music_fd,a[0],0)==(int)a[0])n=read(music_fd,file_result+16,a[1]);}
  if(cmd==12){if(music_fd>=0)close(music_fd);music_fd=-1;n=0;}
  file_result[1]=n;return file_result;
 }
 if(cmd==6)draining=1;
 if(cmd==5 && len==4 && *(unsigned*)buf<=0x7fff)volume=*(unsigned*)buf;
 if(cmd==1){sceSdSetParam(0xf81,0);sceSdSetParam(0x1081,0);sceSdBlockTrans(1,2,0,0);active=0;wr=rd=underruns=interrupts=draining=0;memset(dma,0,sizeof(dma));}
 if(cmd==2 && len==BLOCK && wr-rd<N){memcpy(ring[wr%N],buf,BLOCK);wr++;}
 if(cmd==3 && !active && wr-rd>=2){memcpy(dma,ring[rd++%N],BLOCK);memcpy(dma+BLOCK,ring[rd++%N],BLOCK);CpuSuspendIntr(&s);previous_arg=sceSdGetTransIntrHandlerArgument(1);previous=sceSdSetTransIntrHandler(1,intr,0);active=1;sceSdBlockTrans(1,0x10,dma,sizeof(dma));sceSdSetParam(0xf81,volume);sceSdSetParam(0x1081,volume);CpuResumeIntr(s);}
 if(cmd==4 && active){CpuSuspendIntr(&s);active=0;sceSdSetParam(0xf81,0);sceSdSetParam(0x1081,0);sceSdBlockTrans(1,2,0,0);sceSdSetTransIntrHandler(1,previous,previous_arg);CpuResumeIntr(s);}
 result[0]=0x50434d31;result[1]=wr-rd;result[2]=active;result[3]=underruns;result[4]=interrupts;result[5]=wr;result[6]=rd;return result;
}
static void rpc(void *arg){(void)arg;sceSifInitRpc(0);sceSifSetRpcQueue(&queue,GetThreadId());sceSifRegisterRpc(&server,0x564f5242,dispatch,rpcbuf,0,0,&queue);sceSifRpcLoop(&queue);}
int _start(int argc,char **argv){(void)argc;(void)argv;iop_sema_t sm={0};sm.initial=0;sm.max=4;sema=CreateSema(&sm);iop_thread_t t={0};t.attr=TH_C;t.thread=worker;t.priority=35;t.stacksize=2048;int id=CreateThread(&t);StartThread(id,0);t.thread=rpc;t.priority=45;id=CreateThread(&t);StartThread(id,0);return 0;}
