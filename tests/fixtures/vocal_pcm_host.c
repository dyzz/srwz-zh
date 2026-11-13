/* Host execution of the production PCM state machine, with controlled libsd and
 * interrupt scheduling. This does not emulate SPU2 timing or real IOP latency. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef short s16;
typedef unsigned short u16;
typedef unsigned char u8;
typedef unsigned u32;
typedef struct { unsigned lo, hi; } iop_sys_clock_t;
typedef int SifRpcDataQueue_t;
typedef int SifRpcServerData_t;
typedef int (*sceSdTransIntrHandler)(int, void *);
#define SD_TRANS_STOP 2
#define SD_TRANS_MODE_IO 8
static unsigned mock_st, clock_ticks=100000;
static int fail_start, hw[2], irq_enabled=1, signals, voice_done=1;
static unsigned vols[8192];
static sceSdTransIntrHandler handlers[2];
static void *args[2];
static void (*on_resume)(void);
static void CpuSuspendIntr(int *s){*s=irq_enabled;irq_enabled=0;}
static void CpuResumeIntr(int s){
 irq_enabled=s;
 if(s&&on_resume){void (*f)(void)=on_resume;on_resume=NULL;f();}
}
static void GetSystemTime(iop_sys_clock_t *c){c->hi=clock_ticks>>24;c->lo=clock_ticks<<8;}
static void iSignalSema(int s){(void)s;if(signals<4)signals++;}
static void WaitSema(int s){(void)s;}
static unsigned sceSdBlockTransStatus(int c,int f){(void)c;(void)f;return mock_st;}
static void sceSdSetParam(int a,unsigned v){vols[a]=v;}
static unsigned sceSdGetParam(int a){return vols[a];}
static void *sceSdGetTransIntrHandlerArgument(int c){return args[c];}
static sceSdTransIntrHandler sceSdSetTransIntrHandler(int c,sceSdTransIntrHandler f,void *a){
 sceSdTransIntrHandler p=handlers[c];handlers[c]=f;args[c]=a;return p;
}
static int sceSdBlockTrans(int c,int m,void *p,unsigned n,...){
 (void)p;(void)n;
 if((m&3)==SD_TRANS_STOP){hw[c]=0;return 0;}
 if(fail_start)return -1;
 hw[c]=1;return 0;
}
static int sceSdVoiceTransStatus(int c,int f){(void)c;(void)f;return voice_done;}
static int sceSdVoiceTrans(int c,int m,void *p,void *q,unsigned n){
 (void)c;(void)m;(void)p;(void)q;return n;
}
#include "pcm-under-test.inc"

/* Exercise the actual EE finished-state helper against the actual IOP RPC. */
static unsigned reply[16],telemetry[32],stop_calls,start_calls;
static int call(int cmd,void *buf,int len){
 if(cmd==3)start_calls++;
 memcpy(reply,dispatch(cmd,buf,len),sizeof(reply));return 0;
}
static void player_stop(void){stop_calls++;call(4,NULL,0);}
#include "drain-under-test.inc"

static void reset(void){
 active=wr=rd=rd_off=pend=underruns=interrupts=draining=cur=last_native1=drain_wait=0;
 fresh=-1;fail_start=signals=0;voice_done=irq_enabled=1;on_resume=NULL;clock_ticks=100000;
 memset((void*)native_voice,0,sizeof(native_voice));memset((void*)native_block,0,sizeof(native_block));
 memset((void*)native_io,0,sizeof(native_io));memset(handlers,0,sizeof(handlers));
 memset(hw,0,sizeof(hw));memset(args,0,sizeof(args));memset(vols,0,sizeof(vols));
 memset((void*)stats,0,sizeof(stats));stop_calls=start_calls=0;
}
static void status(int half,unsigned off){
 mock_st=(half<<24)|(((uintptr_t)dma+half*BLOCK+off)&0xffffff);
}
static void tick(int half){status(half,0);intr(cur,NULL);refill();}
static void ee_drain(void){call(0,NULL,0);pump_drain();}
static void finish(void){
 for(int i=0;i<3;i++){
  tick((i+1)&1);ee_drain();
  if(i<2)assert(stop_calls==0);
 }
 assert(stop_calls==1&&!active);
}
static void test_halt(void){
 unsigned char orig[2*BLOCK],expected[2*BLOCK];
 for(int i=0;i<2*BLOCK;i++)orig[i]=(i*31+i/251)%255;
 for(int h=0;h<2;h++)for(int f=0;f<2;f++)for(int off=0;off<=BLOCK;off++){
  reset();memcpy(dma,orig,sizeof(orig));active=1;fresh=f;status(h,off);
  unsigned n=BLOCK-(off&~1023);memcpy(expected,orig+h*BLOCK+(off&~1023),n);
  if(f==1-h){memcpy(expected+n,orig+(1-h)*BLOCK,BLOCK);n+=BLOCK;}
  adma_halt(1);assert(pend==n);assert(memcmp(dma,expected,n)==0);
 }
}
static void test_ring(void){
 unsigned char dst[2*BLOCK];unsigned long long produced=0,consumed=0;
 reset();srand(1);
 for(int step=0;step<10000;step++){
  if((rand()%2)&&wr-rd<N){
   for(int i=0;i<BLOCK;i++)dst[i]=(produced+i)%251;
   dispatch(2,dst,BLOCK);produced+=BLOCK;
  }else{
   unsigned n=(rand()%16+1)*1024;if(n>avail())n=avail();take(dst,n);
   for(unsigned i=0;i<n;i++)assert(dst[i]==(consumed+i)%251);
   consumed+=n;
  }
  assert(rd_off<BLOCK&&wr-rd<=N);assert(wr!=rd||rd_off==0);
  assert(avail()==produced-consumed);
 }
 assert(!underruns);
 /* A partially consumed head still owns its slot when all N slots are used. */
 reset();wr=N;rd_off=1024;unsigned old=wr;dispatch(2,dst,BLOCK);assert(wr==old);
}
static void test_tail_home(void){
 reset();wr=rd=2;active=1;cur=0;fresh=1;hw[0]=1;
 memset(dma,0x11,BLOCK);memset(dma+BLOCK,0x22,BLOCK);status(0,1024);
 call(6,NULL,0); /* This RPC itself runs the home migration. */
 assert(active&&cur==1&&pend==0&&result[1]>0&&!underruns);
 for(int i=0;i<7168;i++)assert(dma[i]==0x11);
 for(int i=7168;i<15360;i++)assert(dma[i]==0x22);
 for(int i=15360;i<16384;i++)assert(dma[i]==0);
 ee_drain();assert(!stop_calls);finish();
}
static void test_busy_tail(void){
 reset();active=1;cur=1;fresh=1;hw[1]=1;draining=1;drain_wait=3;
 memset(dma,0x77,sizeof(dma));status(1,4096);
 native_block[0]=1;yield(1);native_block[1]=1;
 assert(!active&&pend==4096);ee_drain();assert(!active&&!stop_calls&&start_calls==1);
 native_block[1]=0;ee_drain();assert(active&&cur==1&&!stop_calls);
 for(int i=0;i<4096;i++)assert(dma[i]==0x77);
 finish();assert(!underruns);
}
static void test_restart_grace(void){
 reset();wr=2;draining=1;assert(adma_start(1));tick(1);tick(0);
 assert(drain_wait==1);status(0,1024);yield(1);
 assert(active&&cur==0&&drain_wait==3);last_native1=clock_ticks;
 finish();
}
static int native_handler(int ch,void *a){(void)ch;(void)a;return 0;}
static unsigned migrate_from;
static void migrate(void){yield(migrate_from);native_block[migrate_from]=1;}
static void test_handler_race(void){
 for(unsigned target=0;target<2;target++){
  reset();wr=10;active=1;cur=1-target;fresh=1;status(0,1024);
  migrate_from=cur;on_resume=migrate;
  wrap_handler(target,native_handler,(void*)(uintptr_t)(target+1));
  assert(active&&cur==target&&handlers[target]==intr);
  assert(previous[target]==native_handler&&previous_arg[target]==(void*)(uintptr_t)(target+1));
  adma_halt(0);assert(handlers[target]==native_handler&&args[target]==(void*)(uintptr_t)(target+1));
 }
}
static void test_stop_race(void){
 for(unsigned target=0;target<2;target++){
  reset();wr=10;active=1;cur=1-target;fresh=1;native_block[target]=1;status(0,1024);
  migrate_from=cur;on_resume=migrate;
  wrap_block(target,SD_TRANS_STOP,NULL,0,0);
  assert(!active&&!native_block[target]&&!native_io[target]);
  dispatch(3,NULL,0);assert(active&&cur==target&&hw[target]);
 }
}
static void test_failed_start(void){
 for(int once=0;once<2;once++){
  reset();wr=once?1:3;draining=once;fail_start=1;
  memset(ring,0x35,sizeof(ring));handlers[1]=native_handler;args[1]=(void*)1;
  vols[0xf81]=123;vols[0x1081]=234;
  assert(!adma_start(1)&&!active&&pend==2*BLOCK&&!hw[1]);
  assert(handlers[1]==native_handler&&args[1]==(void*)1);
  assert(vols[0xf81]==123&&vols[0x1081]==234);
  unsigned consumed=rd;unsigned char kept[2*BLOCK];memcpy(kept,dma,sizeof(kept));
  assert(!adma_start(1)&&rd==consumed&&memcmp(kept,dma,sizeof(kept))==0);
  call(0,NULL,0);assert(!once||reply[1]>0);
  fail_start=0;assert(adma_start(1)&&active&&hw[1]&&rd==consumed);
  assert(memcmp(kept,dma,sizeof(kept))==0&&!underruns);
  if(once)finish();
 }
}
static void test_stale_signals(void){
 reset();wr=10;assert(adma_start(1));status(0,0);unsigned old=rd;
 for(int i=0;i<4;i++)refill();assert(rd==old);
 tick(1);assert(rd==old+1);for(int i=0;i<4;i++)refill();assert(rd==old+1);
 status(1,1024);yield(1);assert(cur==0);status(0,0);old=rd;
 unsigned before=interrupts;intr(1,NULL);assert(interrupts==before);
 for(int i=0;i<4;i++)refill();assert(rd==old);
}
static void test_stop_reset(void){
 for(int running=0;running<2;running++)for(int cmd=1;cmd<=4;cmd+=3){
  reset();active=running;wr=3;rd=1;rd_off=1024;pend=2048;fresh=1;draining=1;drain_wait=3;
  status(0,1024);dispatch(cmd,NULL,0);
  assert(!active&&!wr&&!rd&&!rd_off&&!pend&&!draining&&!drain_wait&&fresh==-1);
  dispatch(3,NULL,0);assert(!active);
 }
}
static void test_short_once(void){
 reset();wr=1;memset(ring[0],0x62,BLOCK);call(6,NULL,0);ee_drain();
 assert(active&&rd==1&&!underruns);finish();
 reset();call(6,NULL,0);ee_drain();assert(stop_calls==1&&!active);
}
int main(int argc,char **argv){
 assert(argc==2);
 #define TEST(name) if(!strcmp(argv[1],#name)){test_##name();puts("PASS " #name);return 0;}
 TEST(halt) TEST(ring) TEST(tail_home) TEST(busy_tail) TEST(restart_grace)
 TEST(handler_race) TEST(stop_race) TEST(failed_start) TEST(stale_signals)
 TEST(stop_reset) TEST(short_once)
 return 2;
}
