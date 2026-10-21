/* Native chain send, with readiness precondition (CHCR bit100 is clear).
 * Channel is a byte buffer here, not hardware. Wait/timeout and cache syscall
 * behavior are outside this value/write-order model.
 */
#include <stdint.h>
static uint32_t dm_r32(const uint8_t*p){return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void dm_w32(uint8_t*p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
uint32_t native_dma_address_model(uint32_t address){return address>>28==7?(address&0x0fffffffu)|0x80000000u:address;}
uint32_t native_dma_send_ready_model(uint8_t *channel,uint32_t chain){
 if(dm_r32(channel)&0x100)return 0; /* analysis precondition, no native shortcut */
 if(dm_r32(channel+0x30)!=0xffffffffu)dm_w32(channel+0x30,native_dma_address_model(chain));
 dm_w32(channel+0x20,0);
 uint32_t control=(dm_r32(channel)&0xfffffff3u)|0x105u;dm_w32(channel,control);return control;
}
