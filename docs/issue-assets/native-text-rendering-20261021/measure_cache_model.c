/* Reconstructed cache writer tail and the two draw-argument blocks only.
 * Prefix initialization, intervening graphics/style calls and draw bodies are
 * external boundaries. This models the actual 16-bit center-offset cache.
 */
#include "core_model.c"
#include <string.h>
static uint16_t cache_r16(const uint8_t*p){return p[0]|((uint16_t)p[1]<<8);}
static void cache_w16(uint8_t*p,uint16_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);}
void native_center_cache_model(uint8_t *state,uint8_t *object,const uint8_t *first,const uint8_t *second,int32_t *raw){
 raw[0]=native_measure_model((FontState*)state,first,0);cache_w16(object+0x24,(uint16_t)raw[0]);
 raw[1]=native_measure_model((FontState*)state,second,0);cache_w16(object+0x26,(uint16_t)raw[1]);
}
void native_center_cache_args_model(const uint8_t*object,int second,int16_t x,int16_t y,int16_t color,uint32_t packet,uint32_t *args){
 memcpy(args,object+(second?0x20:0x1c),4);
 args[1]=(uint32_t)((int32_t)x+(int16_t)cache_r16(object+(second?0x26:0x24))+(second?0x224:0x5a));
 args[2]=(uint32_t)((int32_t)y+6);args[3]=packet;
 args[4]=(uint32_t)((int32_t)color+0xffff9c);args[5]=0;
}
