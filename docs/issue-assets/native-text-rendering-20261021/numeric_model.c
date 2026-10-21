/* Reconstructed native number and fixed-seed symbol record producers.
 * All buffer-capacity errors are analysis bounds, absent from native code.
 * Immediate packet output is supplied by packet_model.c.
 */
#include "parse_model.c"
extern uint32_t native_packet_model(uint8_t*,size_t,uint32_t,int,const uint8_t*,unsigned,const uint8_t*,unsigned,int16_t,int16_t,const uint8_t*,size_t*);
static void secondary_record(uint8_t *f,uint8_t *r,int16_t u,int16_t v,int16_t x,int16_t y,uint8_t width){
 w16(r,(uint16_t)u);w16(r+2,(uint16_t)v);w16(r+4,(uint16_t)x);w16(r+6,(uint16_t)y);w32(r+8,r32(f+0x34));
 r[0xc]=width;r[0xd]=(uint8_t)r16(f+0x2e);r[0xe]=(uint8_t)r16(f+0x32);r[0xf]=0x24;r[0x10]=f[0x4a];
 w32(r+0x14,r32(f+0x24));w32(r+0x18,r32(f+0x28));r[0x1c]=f[0x50];
}
int native_number_records_model(uint8_t *f,uint8_t *records,int32_t value,int16_t x,int16_t y,int right,uint32_t z,unsigned capacity){
 unsigned digits=1;int32_t divisor=1;
 if(value>=2){int32_t n=value;digits=0;do{digits++;n/=10;}while(n);for(unsigned i=1;i<digits;i++)divisor*=10;}
 if(z!=0xffffffffu)w32(f+0x34,z);
 int16_t width=s16(f+0x2c),advance=s16(f+0x30);
 if(right)x=(int16_t)(x-(int16_t)(width+(int32_t)(digits-1)*advance));
 w16(f+0x6a,(uint16_t)x);unsigned slot=r16(f+2);
 for(unsigned i=0;i<digits;i++){
  if(slot>=capacity)return -1;
  int32_t q=value/divisor;secondary_record(f,records+slot*32,(int16_t)((uint32_t)(q+1)*24u),0,x,y,(uint8_t)width);
  x=(int16_t)(x+advance);unsigned count=(r16(f+2)+1)&65535;w16(f+2,(uint16_t)count);slot++;
  if(count==255){w16(f+2,254);slot--;}
  value=(int32_t)((uint32_t)value-(uint32_t)((int64_t)q*divisor));divisor/=10;
 }
 w16(f+0x68,(uint16_t)x);return 0;
}
int native_symbol_records_model(uint8_t *f,uint8_t *records,const uint8_t *text,const uint8_t *seed,unsigned seed_count,int16_t x,int16_t y,int32_t advance,uint32_t z,unsigned capacity){
 if(z!=0xffffffffu)w32(f+0x34,z);w16(f+0x6a,(uint16_t)x);unsigned slot=r16(f+2);
 for(unsigned guard=0;guard<4096;guard++,text+=2){
  uint16_t key=r16(text);if(!key)return 0;unsigned index=0;
  while(index<seed_count&&r16(seed+index*2)!=key)index++;
  if(index==seed_count||slot>=capacity)return -1;
  secondary_record(f,records+slot*32,(int16_t)((index%21)*24),(int16_t)((index/21)*24),x,y,(uint8_t)advance);
  x=(int16_t)((uint32_t)(int32_t)x+(uint32_t)advance);w16(f+2,(uint16_t)(r16(f+2)+1));slot++;
 }
 return -1;
}
/* Finish the common immediate numeric/symbol path: exclude existing records
 * and primary queue, emit newly produced secondary records, restore counts. */
uint32_t native_secondary_immediate_model(uint8_t *f,const uint8_t *records,uint16_t old_primary,uint16_t old_secondary,uint8_t *packet,size_t capacity,uint32_t pointer,int chain,const uint8_t *templates,size_t *written){
 if(!pointer){*written=0;return 0;}
 unsigned count=(uint16_t)(r16(f+2)-old_secondary);
 uint32_t result=native_packet_model(packet,capacity,pointer,chain,0,0,records+old_secondary*32,count,s16(f+4),s16(f+6),templates,written);
 w16(f,old_primary);w16(f+2,old_secondary);return result;
}
int native_record_group_model(uint8_t *records,unsigned index,unsigned slots){
 unsigned first=index*66;if(first+66>slots)return -1;
 for(unsigned i=first;i<first+66;i++){
  uint8_t *r=records+i*32;w16(r,0);w16(r+2,0);w16(r+4,0);w16(r+6,(uint16_t)-200);w32(r+8,0);w16(r+0xc,1);w16(r+0xe,1);r[0x10]=128;
 }
 return 0;
}
