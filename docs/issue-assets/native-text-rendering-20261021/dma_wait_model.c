/* Native integer timeout/recovery model. Device registers are supplied as RAM
 * values. Interrupt entry/exit and diagnostics are declared external services.
 * ready_poll is a supplied device schedule, 0 means continuously busy.
 */
#include "submission_model.c"
#define DM_LIMIT 0x1000000u
static void dw_event(uint32_t *events,unsigned *count,uint32_t address,uint32_t value){
 events[2*(*count)]=address;events[2*(*count)+1]=value;(*count)++;
}
uint32_t native_dma_recovery_model(uint8_t *channel,uint32_t base,uint32_t enable_read,
 uint32_t *enable_write,uint32_t *events,unsigned *count){
 if(!(enable_read&0x10000u)){*enable_write=enable_read|0x10000u;dw_event(events,count,0x1000f590u,*enable_write);}
 uint32_t saved=dm_r32(channel);dm_w32(channel,saved&0xfffffeffu);dw_event(events,count,base,saved&0xfffffeffu);
 *enable_write=enable_read;dw_event(events,count,0x1000f590u,*enable_write);return saved;
}
uint32_t native_dma_wait_value_model(uint8_t *channel,uint32_t base,uint32_t ready_poll,uint32_t enable_read,
 uint32_t *enable_write,uint32_t *events,unsigned *count,unsigned *diagnostics){
 *diagnostics=0;
 if(!(dm_r32(channel)&0x100u))return 0;
 if(ready_poll&&ready_poll<=DM_LIMIT+1u){dm_w32(channel,dm_r32(channel)&0xfffffeffu);return 0;}
 *diagnostics=1;native_dma_recovery_model(channel,base,enable_read,enable_write,events,count);return 0;
}
uint32_t native_dma_wait_send_model(uint8_t *channel,uint32_t base,uint32_t chain,uint32_t ready_poll,uint32_t enable_read,
 uint32_t *enable_write,uint32_t *events,unsigned *count,unsigned *diagnostics){
 native_dma_wait_value_model(channel,base,ready_poll,enable_read,enable_write,events,count,diagnostics);
 if(dm_r32(channel+0x30)!=0xffffffffu)dw_event(events,count,base+0x30,native_dma_address_model(chain));
 dw_event(events,count,base+0x20,0);dw_event(events,count,base,(dm_r32(channel)&0xfffffff3u)|0x105u);
 return native_dma_send_ready_model(channel,chain);
}
