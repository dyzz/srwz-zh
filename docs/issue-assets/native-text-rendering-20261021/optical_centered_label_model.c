/* Whole upper centered-label routine reconstructed through separately proved
 * reset, measure, parser and packet semantics. Caller sets class metrics to
 * 16x10/advance16x10; explicit metrics remain reset defaults 22x11.
 */
#include "parse_model.c"
extern uint32_t native_packet_model(uint8_t*,size_t,uint32_t,int,const uint8_t*,unsigned,const uint8_t*,unsigned,int16_t,int16_t,const uint8_t*,size_t*);
uint32_t native_optical_centered_label_model(uint8_t *f,uint8_t *records,uint16_t *pending,unsigned *pending_count,const uint8_t *text,const uint8_t *extended,const uint8_t *style13,uint8_t *packet,size_t capacity,uint32_t pointer,const uint8_t *templates,int32_t *center_x,size_t *written){
 native_reset_model(f);w16(f+0x1c,style13[0]);w16(f+0x32,style13[0]);memcpy(f+0x24,style13+1,8);
 const uint16_t metrics[8]={16,10,16,10,16,10,16,10};for(unsigned i=0;i<8;i++)w16(f+0x38+i*2,metrics[i]);w16(f+0x48,1);memset(f+0x4b,1,5);
 *center_x=native_measure_model((FontState*)f,text,0);w16(f+0x10,(uint16_t)*center_x);w16(f+0x12,89);
 unsigned old_primary=r16(f),old_secondary=r16(f+2);const uint8_t *subs[4]={text,text,text,text};
 int early=native_parse_model_impl(f,records,pending,pending_count,text,extended,subs,0x00ffff50,320,4096,3);
 uint32_t ret=pointer;*written=0;
 if(pointer&&!early){
  unsigned count=(uint16_t)(r16(f)-old_primary);ret=native_packet_model(packet,capacity,pointer,0,records+old_primary*32,count,0,0,s16(f+4),s16(f+6),templates,written);w16(f,(uint16_t)old_primary);w16(f+2,(uint16_t)old_secondary);
 }
 w32(f+0x24,0x80808080);w32(f+0x28,0x80808080);f[0x50]=0;return ret;
}
