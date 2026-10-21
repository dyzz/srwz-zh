/* Cached-symbol initializer reconstructed from symbol records and GIF model.
 * Does not clear the lazy flag: callers own that operation.
 */
#include "numeric_model.c"
int native_cache_setup_model(uint8_t *f,uint8_t *records,const uint8_t *seed,uint8_t *first,uint8_t *second,uint32_t temporary_pointer,const uint8_t *templates){
 uint8_t shear=f[0x4a],outline=f[0x50];uint16_t p=r16(f),s=r16(f+2);f[0x4a]=0;f[0x50]=0;
 const uint8_t strings[2][4]={{0x81,0x5b,0,0},{0x81,0x7c,0,0}};
 for(unsigned i=0;i<2;i++){
  uint8_t packet[512];size_t written=0;memset(packet,0xa5,sizeof(packet));
  if(native_symbol_records_model(f,records,strings[i],seed,42,0,0,0,0,400))return -1;
  native_secondary_immediate_model(f,records,p,s,packet,sizeof(packet),temporary_pointer,0,templates,&written);
  if(written<208)return -2;
  memcpy(i?second:first,packet,208);
 }
 f[0x4a]=shear;f[0x50]=outline;return 0;
}
