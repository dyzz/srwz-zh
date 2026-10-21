/* Complete native encyclopedia row-range composition for valid bounded rows.
 * Input byte-line selection is shared with split_model.c. No GS execution.
 * cfg: first,last,packet_reference_present,pointer,physical_packet_base,fade,
 *      output_physical_row_call_count, patch_flags (bit0 explicit_sync, bit1 safe_height, bit2 optical_candidate). ctx: x,y,z,rgba,palette,force_palette.
 * Capacity/guard failures are analysis bounds absent from native code.
 */
#include "parse_model.c"
#include "split_model.c"
extern uint32_t native_packet_model(uint8_t*,size_t,uint32_t,int,const uint8_t*,unsigned,const uint8_t*,unsigned,int16_t,int16_t,const uint8_t*,size_t*);
static int render_row(uint8_t *f,uint8_t *records,uint16_t *pending,unsigned *n,const uint8_t *text,const uint8_t *desc,int16_t x,int16_t y,uint32_t *cfg,uint32_t *ctx,const uint8_t *colors,uint8_t *packet,size_t capacity,const uint8_t *templates,const uint8_t *extended){
 if(cfg[7]&1)for(unsigned i=0;i<4;i++)w16(f+0x14+2*i,desc[0xe + i]);
 for(unsigned i=0;i<8;i++)w16(f+0x38+2*i,(uint16_t)(int16_t)(int8_t)desc[0xe + i]);w16(f+0x48,1);memset(f+0x4b,1,5);
 int32_t color=(int8_t)desc[0];ctx[0]=(uint32_t)(int32_t)x;ctx[1]=(uint32_t)(int32_t)y;ctx[2]=r32(desc+0x18);int found=0;
 for(unsigned i=0;i<11;i++)if(r32(colors+i*8)==(uint32_t)color){const uint8_t *p=colors+i*8+4;ctx[3]=((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];ctx[5]=0;found=1;break;}
 if(!found){ctx[4]=(uint32_t)color;ctx[5]=1;}
 if(!cfg[2])return 0;
 w16(f+0x10,(uint16_t)x);w16(f+0x12,(uint16_t)y);w32(f+0x20,ctx[2]);f[0x27]=(uint8_t)ctx[3];
 if(ctx[5]){w16(f+0x1c,(uint16_t)ctx[4]);memset(f+0x24,cfg[5]==64?64:128,3);}
 else{w16(f+0x1c,0);f[0x24]=(uint8_t)(ctx[3]>>24);f[0x25]=(uint8_t)(ctx[3]>>16);f[0x26]=(uint8_t)(ctx[3]>>8);if(cfg[5]==64)for(unsigned i=0;i<3;i++)f[0x24+i]>>=1;}
 unsigned old_primary=r16(f),old_secondary=r16(f+2);const uint8_t empty[2]={0,0};const uint8_t *subs[4]={empty,empty,empty,empty};
 int early=native_parse_model_impl(f,records,pending,n,text,extended,subs,0xffffffffu,320,4096,cfg[7]>>1);
 if(cfg[3]&&!early){
  unsigned count=(uint16_t)(r16(f)-old_primary);uint32_t offset=(cfg[3]&0x0fffffffu)-cfg[4];if(offset>=capacity)return -1;size_t written=0;
  cfg[3]=native_packet_model(packet+offset,capacity-offset,cfg[3],0,records+old_primary*32,count,0,0,s16(f+4),s16(f+6),templates,&written);w16(f,(uint16_t)old_primary);w16(f+2,(uint16_t)old_secondary);
 }
 memset(f+0x24,128,4);return 0;
}
int native_library_range_model(uint8_t *f,uint8_t *records,uint16_t *pending,unsigned *n,const uint8_t *text,uint32_t *cfg,const uint8_t *desc,uint8_t *scratch,size_t scratch_capacity,uint32_t *ctx,const uint8_t *colors,uint8_t *packet,size_t packet_capacity,const uint8_t *templates,const uint8_t *extended){
 int32_t first=(int32_t)cfg[0],last=(int32_t)cfg[1];cfg[6]=0;
 if(!text||!*text||first<0||last<0||last<first)return 0;
 int16_t x=s16(desc+2);int32_t y=s16(desc+4);int32_t remaining=(int32_t)((uint32_t)last-(uint32_t)first+1u);const uint8_t *cursor=text;
 for(unsigned guard=0;guard<1024;guard++){
  uint32_t offset=0,length=0;if(!native_select_byte_line_model(cursor,first,&offset,&length,10))return 1;
  if(length>=scratch_capacity)return -1;memcpy(scratch,cursor+offset,length);scratch[length]=0;first=0;
  if(render_row(f,records,pending,n,scratch,desc,x,(int16_t)y,cfg,ctx,colors,packet,packet_capacity,templates,extended))return -1;cfg[6]++;
  remaining=(int32_t)((uint32_t)remaining-1u);cursor+=offset+length;
  if(remaining<=0||!*cursor)return 1;
  cursor++;y=(int32_t)((uint32_t)y+(uint32_t)(int32_t)(int8_t)desc[0x11]);
 }
 return -2;
}
