/* Reconstructed native 13C5C0: CPU scatter from 24x24 4bpp glyphs into
 * a 512-pixel-wide, 480-row atlas (256 byte row pitch). No GS upload here.
 * caller supplies a valid destination range and glyph indices.
 */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
int native_scatter_model(uint8_t *atlas,size_t atlas_size,const uint8_t *font,size_t font_size,
 const uint16_t *indices,unsigned count,int16_t start_x,int16_t start_y){
 int16_t x=start_x,y=start_y;
 for(unsigned i=0;i<count;i++){
  size_t source=(size_t)indices[i]*288;
  /* Native SRA x,1 rounds negative values down. Invalid negative destinations
   * are rejected only by this analysis bound, not by the original function. */
  int byte_x=x>=0?x/2:-((-(int)x+1)/2);
  int dest=(int)y*256+byte_x;
  if(source+288>font_size||dest<0||(size_t)dest+23*256+12>atlas_size)return -1;
  for(unsigned row=0;row<24;row++)memcpy(atlas+(size_t)dest+row*256,font+source+row*12,12);
  x=(int16_t)(x+24);if(x>=504){x=0;y=(int16_t)(y+24);}
 }
 return 0;
}
/* Native 13A260: copy reserved atlas marker to current allocator position. */
void native_atlas_restore_model(uint8_t *state){memcpy(state+8,state+12,4);}
/* Native 13C390: low signed byte of argument is the actual predicate.
 * This helper is callable at batch boundaries as well as frame boundaries.
 */
void native_frame_clear_model(uint8_t *state,uint16_t *pending_count,uint32_t *write_pointer,
 int64_t arg,uint32_t native_index_base){
 if((int8_t)arg){memset(state,0,4);native_atlas_restore_model(state);*pending_count=0;*write_pointer=native_index_base;}
}
