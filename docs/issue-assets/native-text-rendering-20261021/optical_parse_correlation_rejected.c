/* Reconstructed 13A290 integer parsing/record-building path with a1==0.
 * Does not emit GIF packets (13ACA0). Pointer globals are supplied as arrays.
 * Inputs must be native well-terminated byte streams; nested substitutions
 * intentionally retain the native single saved-return-pointer behavior.
 */
#include <stdint.h>
#include <string.h>
#include "core_model.c"
static uint16_t r16(const uint8_t *p){return p[0]|((uint16_t)p[1]<<8);}
static int16_t s16(const uint8_t *p){return (int16_t)r16(p);}
static uint32_t r32(const uint8_t *p){return r16(p)|((uint32_t)r16(p+2)<<16);}
static void w16(uint8_t *p,uint16_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);}
static void w32(uint8_t *p,uint32_t v){w16(p,(uint16_t)v);w16(p+2,(uint16_t)(v>>16));}
static void native_reset_model(uint8_t *f){
 w16(f+0x10,0);w16(f+0x12,0);
 w16(f+0x14,22);w16(f+0x16,11);w16(f+0x18,22);w16(f+0x1a,11);w16(f+0x1c,0);
 w32(f+0x20,0x00ffffff);w32(f+0x24,0x80808080);w32(f+0x28,0x80808080);
 w16(f+0x2c,18);w16(f+0x2e,11);w16(f+0x30,16);w16(f+0x32,0);w32(f+0x34,0x00ffffff);
 for(int off=0x38;off<=0x44;off+=4){w16(f+off,22);w16(f+off+2,11);}
 w16(f+0x48,0);memset(f+0x4a,0,7);
}
/* Return 1 for atlas exhaustion, 0 for normal termination. pending_count is
 * the native GP halfword for glyph upload requests, not the record count.
 * extra allocation bounds here protect the analysis harness only; native
 * source has no matching error return (-1). */
static int native_parse_model_impl(uint8_t *f,uint8_t *records,uint16_t *pending,
 unsigned *pending_count,const uint8_t *input,const uint8_t *extended,
 const uint8_t *const substitutions[4],uint32_t z_arg,unsigned record_slots,unsigned pending_slots,int safe_height){
 int16_t ax=s16(f+8),ay=s16(f+10),x=s16(f+0x10),y=s16(f+0x12);
 int16_t ew=s16(f+0x14),eh=s16(f+0x16),advx=s16(f+0x18),advy=s16(f+0x1a);
 int16_t saved_mode=s16(f+0x48);const uint8_t *p=input,*saved_p=0;int replacing=0,early=0;
 unsigned guard=0;
 unsigned slot=r16(f);if(z_arg!=0xffffffffu)w32(f+0x20,z_arg);
 for(;guard<100000;guard++){
  unsigned first=*p++;
  if(first==0x0a)first=0x2e;else if(first==0)first=0x2f;
  if(first==0x2f){if(replacing){replacing=0;p=saved_p;continue;}break;}
  if(first==0x2e){x=s16(f+0x10);y=(int16_t)(y+advy);continue;}
  if(first==0x30){p++;native_reset_model(f);continue;}
  if(first>=0x31&&first<=0x39){
   unsigned v=*p++;
   switch(first){
   case 0x31:w16(f+0x1c,(uint16_t)v);break;
   case 0x32:ew=(int16_t)v;w16(f+0x14,(uint16_t)v);w16(f+0x48,0);break;
   case 0x33:{
    unsigned raw=v;
    if((safe_height&2)&&v>=0x8b&&v<=0x8e)v-=0x80;
    if(safe_height&&v==0x8a)v=10;
    eh=(int16_t)(((safe_height&2)&&raw>=0x8b&&raw<=0x8e)?raw:v);
    w16(f+0x16,(uint16_t)v);w16(f+0x48,0);break;
   }
   case 0x34:advx=(int16_t)v;w16(f+0x18,(uint16_t)v);w16(f+0x48,0);break;
   case 0x35:advy=(int16_t)v;w16(f+0x1a,(uint16_t)v);w16(f+0x48,0);break;
   case 0x36:w16(f+0x32,(uint16_t)v);break;
   case 0x37:w16(f+0x2c,(uint16_t)v);break;
   case 0x38:w16(f+0x2e,(uint16_t)v);break;
   case 0x39:w16(f+0x30,(uint16_t)v);break;
   }
   continue;
  }
  if(first>=0x3a&&first<=0x3d){replacing=1;saved_p=p;p=substitutions[first-0x3a];first=*p++;}
  uint16_t code=(uint16_t)((first<<8)|*p++);
  int16_t rw=ew,rh=eh;advx=s16(f+0x18);advy=s16(f+0x1a);
  if(s16(f+0x48)){
   int off=native_draw_uses_b((const FontState*)f,code)?0x40:0x38;
   rw=s16(f+off);rh=s16(f+off+2);advx=s16(f+off+4);advy=s16(f+off+6);
  }
  uint16_t glyph=native_glyph_resolve_model(code,extended);
  if(slot>=record_slots)return -1;
  uint8_t *rec=records+slot*32;
  if(((code>=0x824f&&code<0x8259)||code==0x8140)&&r32(f+0x88)==0){
   rec[0x11]=0x24;w16(rec+2,0);w16(rec,code==0x8140?0:(uint16_t)((code-0x824e)*24));
  }else{
   if(ay>=480){early=1;break;}
   if(*pending_count>=pending_slots)return -1;
   pending[(*pending_count)++]=glyph;
   w16(rec,(uint16_t)ax);w16(rec+2,(uint16_t)(ay>=240?ay-240:ay));rec[0x11]=(uint8_t)(ay>=240?0x2c:0x24);
   ax=(int16_t)(ax+24);if(ax>=504){ax=0;ay=(int16_t)(ay+24);}
  }
  int16_t record_y=y;
  if((safe_height&2)&&!s16(f+0x48)&&(int32_t)rh-(int32_t)s16(f+0x16)==128){
   rh=s16(f+0x16);record_y=(int16_t)(y-1);
  }
  w16(rec+4,(uint16_t)x);w16(rec+6,(uint16_t)record_y);w32(rec+8,r32(f+0x20));
  w16(rec+0xc,(uint16_t)rw);w16(rec+0xe,(uint16_t)rh);rec[0x10]=(uint8_t)r16(f+0x1c);rec[0x12]=f[0x4a];
  w32(rec+0x14,r32(f+0x24));w32(rec+0x18,r32(f+0x28));rec[0x1c]=f[0x50];
  x=(int16_t)(x+advx);unsigned count=(r16(f)+1)&65535u;w16(f,(uint16_t)count);slot++;
  if(count==0x13f){w16(f,(uint16_t)(count-1));slot--;}
 }
 if(guard>=100000)return -2; /* analysis-only runaway guard */
 w16(f+8,(uint16_t)ax);w16(f+10,(uint16_t)ay);w16(f+0x10,(uint16_t)x);w16(f+0x12,(uint16_t)y);
 if(!early)w16(f+0x48,(uint16_t)saved_mode);
 return early;
}
/* Stock entry retains all native parameter meanings. */
int native_parse_model(uint8_t *f,uint8_t *records,uint16_t *pending,
 unsigned *pending_count,const uint8_t *input,const uint8_t *extended,
 const uint8_t *const substitutions[4],uint32_t z_arg,unsigned record_slots,unsigned pending_slots){
 return native_parse_model_impl(f,records,pending,pending_count,input,extended,substitutions,z_arg,record_slots,pending_slots,0);
}
/* Expose the native parameter reset independently of stream parsing. */
void native_font_state_reset_model(uint8_t *state){native_reset_model(state);}
