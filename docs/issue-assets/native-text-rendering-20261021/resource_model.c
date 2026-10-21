/* Reconstructed native font initialization's state/data effects. External
 * archive I/O, allocation and GS upload are represented by supplied buffers
 * and addresses. These external services are not emulated by this model.
 */
#include "parse_model.c"
extern int32_t native_font_decode_model(const uint8_t*,size_t,uint8_t*,size_t,size_t*,size_t*,int*);
extern int native_scatter_model(uint8_t*,size_t,const uint8_t*,size_t,const uint16_t*,unsigned,int16_t,int16_t);
int native_resource_state_model(uint8_t *f,uint8_t *records,uint16_t *pending,unsigned *count,
 uint8_t *atlas,uint8_t *font,uint8_t *temporary,const uint8_t *font_source,size_t font_size,
 const uint8_t *aux_source,size_t aux_size,const uint8_t *seed,const uint8_t *extended,
 const uint32_t *allocated_addresses){
 size_t consumed,written;int error;
 *count=0;
 if(native_font_decode_model(aux_source,aux_size,temporary,65536,&consumed,&written,&error)!=32832||error)return -1;
 w16(f,0);w16(f+2,0);w16(f+4,2048);w16(f+6,2048);
 w16(f+8,0);w16(f+10,0);w16(f+0x10,0);w16(f+0x12,0);
 w32(f+0x58,allocated_addresses[0]);w32(f+0x60,allocated_addresses[1]);
 w32(f+0x80,allocated_addresses[2]);memset(atlas,0,0x1e000);
 w32(f+0x78,allocated_addresses[3]);
 if(native_font_decode_model(font_source,font_size,font,0x13b000,&consumed,&written,&error)!=0x13b000||error)return -1;
 w16(f+0x14,16);w32(f+0x88,1);
 const uint8_t *empty[4]={(const uint8_t*)"",(const uint8_t*)"",(const uint8_t*)"",(const uint8_t*)""};
 if(native_parse_model(f,records,pending,count,seed,extended,empty,0xffffffffu,320,512))return -1;
 w16(f+12,0);w16(f+14,0);
 if(native_scatter_model(atlas,0x1e000,font,0x13b000,pending,*count,0,0))return -1;
 w32(f+0x88,0);w16(f,0);memcpy(f+12,f+8,4);native_reset_model(f);
 return 0;
}
