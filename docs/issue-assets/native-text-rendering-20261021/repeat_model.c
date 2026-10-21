/* Cached-symbol @N branch after native decimal parsing and lazy setup.
 * Reconstructs final cache mutations and every packet byte, including the
 * update-after-copy ordering. capacity guards are analysis only.
 */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
static uint16_t r16(const uint8_t*p){return p[0]|((uint16_t)p[1]<<8);}
static int16_t s16(const uint8_t*p){return (int16_t)r16(p);}
static uint32_t r32(const uint8_t*p){return r16(p)|((uint32_t)r16(p+2)<<16);}
static void w16(uint8_t*p,uint16_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);}
static void w32(uint8_t*p,uint32_t v){w16(p,(uint16_t)v);w16(p+2,(uint16_t)(v>>16));}
uint32_t native_repeat_model(uint8_t *out,size_t capacity,uint32_t address,uint8_t *cache,const uint8_t *state,int32_t count,int16_t x,int16_t y,uint32_t z,size_t *written){
 if(count>32767)count=32767;
 size_t n=count>0?(size_t)count:0;*written=144+n*64;if(*written>capacity)return 0;
 int16_t px=(int16_t)((int32_t)x+2048);uint32_t py=(uint32_t)((int32_t)y+2048),bottom=py+(uint32_t)(int32_t)s16(state+0x42);
 w16(cache+128,(uint16_t)((uint32_t)count+32768u));cache[159]=(uint8_t)r16(state+0x1c);
 uint8_t *unit=cache+144;w32(unit+16,r32(state+0x24));w32(unit+32,((uint32_t)(int32_t)px<<4)|(py<<20));w32(unit+36,z);
 w32(unit+48,((uint32_t)((int32_t)px+s16(state+0x40))<<4)|(bottom<<20));w32(unit+52,z);
 memcpy(out,cache,144);
 for(size_t i=0;i<n;i++){
  memcpy(out+144+i*64,unit,64);px=(int16_t)((int32_t)px+s16(state+0x44));
  w32(unit+32,((uint32_t)(int32_t)px<<4)|(py<<20));w32(unit+48,((uint32_t)((int32_t)px+s16(state+0x40))<<4)|(bottom<<20));
 }
 return address+(uint32_t)*written;
}
