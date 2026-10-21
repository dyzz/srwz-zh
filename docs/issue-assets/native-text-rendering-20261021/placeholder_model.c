/* Negative numeric values encode repeated-minus placeholders; nonnegative
 * values forward to the ordinary number producer. No decimal minus sign.
 */
#include "cache_setup_model.c"
uint32_t native_placeholder_model(uint8_t *out,size_t capacity,uint32_t pointer,uint8_t *cache,uint8_t *f,uint8_t *records,const uint8_t *templates,const uint8_t *style_table,uint8_t *last_style,int32_t value,int16_t x,int16_t y,int right,uint32_t z,int style,size_t *written){
 *written=0;
 if(value>=0){
  uint16_t p=r16(f),s=r16(f+2);
  if(native_number_records_model(f,records,value,x,y,right,z,400))return 0;
  return native_secondary_immediate_model(f,records,p,s,out,capacity,pointer,0,templates,written);
 }
 int32_t count=(int32_t)(0u-(uint32_t)value);if(count>32767)count=32767;
 unsigned n=count>0?(unsigned)count:0;*written=144+(size_t)n*64;if(*written>capacity)return 0;
 int16_t px;
 if(right)px=(int16_t)((uint32_t)((int32_t)x+2048)-(uint32_t)count*(uint32_t)(int32_t)s16(f+0x30)-(uint32_t)(int32_t)s16(f+0x2c)+(uint32_t)(int32_t)s16(f+0x30));
 else px=(int16_t)((int32_t)x+2048);
 uint32_t py=(uint32_t)((int32_t)y+2048),bottom=py+(uint32_t)(int32_t)s16(f+0x2e);
 int8_t selected=(int8_t)style;
 if(selected!=-1){
  const uint8_t *row=style_table+(int)selected*9;*last_style=(uint8_t)style;w16(f+0x1c,row[0]);w16(f+0x32,row[0]);memcpy(f+0x24,row+1,8);
 }
 w16(cache+128,(uint16_t)((uint32_t)count+32768u));cache[159]=(uint8_t)r16(f+0x32);
 uint8_t *unit=cache+144;w32(unit+16,r32(f+0x24));w32(unit+32,((uint32_t)(int32_t)px<<4)|(py<<20));w32(unit+36,z);
 w32(unit+48,((uint32_t)((int32_t)px+s16(f+0x2c))<<4)|(bottom<<20));w32(unit+52,z);memcpy(out,cache,144);
 for(unsigned i=0;i<n;i++){
  memcpy(out+144+(size_t)i*64,unit,64);px=(int16_t)((int32_t)px+s16(f+0x30));w32(unit+32,((uint32_t)(int32_t)px<<4)|(py<<20));w32(unit+48,((uint32_t)((int32_t)px+s16(f+0x2c))<<4)|(bottom<<20));
 }
 return pointer+(uint32_t)*written;
}
