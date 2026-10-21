/* Complete native two-entity presentation/cache initializer, including its
 * small helpers, font preset and both measurements. Entities retain neutral
 * names: the producer of entity+28 and higher-level lifecycle are not known.
 * All VA-bearing fields are read through the supplied EE RAM image.
 */
#include "core_model.c"
#include "preset_model.c"
static uint16_t src_r16(const uint8_t*p){return p[0]|((uint16_t)p[1]<<8);}
static uint32_t src_r32(const uint8_t*p){return src_r16(p)|((uint32_t)src_r16(p+2)<<16);}
static void src_w16(uint8_t*p,uint16_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);}
static void src_w32(uint8_t*p,uint32_t v){src_w16(p,(uint16_t)v);src_w16(p+2,(uint16_t)(v>>16));}
static unsigned src_category(const uint8_t*ram,uint32_t entity){
 if(!entity)return 4;
 unsigned v=ram[entity+0x25];return v<4?0:v<8?1:v<12?2:3;
}
static unsigned src_shape(const uint8_t*ram,uint32_t entity){
 if(!entity)return 0;
 if(src_r32(ram+entity+8)&&!src_r32(ram+entity+12)&&!src_r32(ram+entity+16))return 3;
 return ram[entity+0x19]&3;
}
static int src_special(const uint8_t*ram,uint32_t entity){
 if(!entity)return 0;
 uint32_t p=src_r32(ram+entity+8);if(!p)return 0;
 p=src_r32(ram+p+0xa8);return p&&(ram[p+0x30]&0x44);
}
uint32_t native_two_entity_cache_model(uint8_t*ram,uint32_t first,uint32_t second,const uint32_t*c){
 /* c: object, font-state, preset-table, selector, icon-pairs, shape-pointers,
  * default text pointer, preset index, edition-specific action/category/palette/shape IDs. */
 uint8_t*o=ram+c[0];unsigned side=1;
 if(first&&second){unsigned a=ram[first+0x25],b=ram[second+0x25];side=(a<b||(a==b&&b<12));}
 const unsigned category_byte[5]={10,9,14,16,0};
 const uint32_t *category_icon=c+10;
 const uint32_t *shape_icon=c+16;
 for(unsigned phase=0;phase<2;phase++){
  uint32_t p=phase?second:first;unsigned slot=side^phase,category=src_category(ram,p);
  if(p){unsigned byte=ram[p+0x19];ram[p+0x19]=(uint8_t)((byte&0xfc)|((byte&3)%3));}
  o[slot]=(uint8_t)category_byte[category];
  src_w16(o+6+slot*2,src_r16(ram+c[4]+category*4+phase*2));src_w16(o+0x28+slot*2,(uint16_t)c[8+phase]);
  if(category<4){src_w16(o+2+slot*2,category_icon[category]);src_w16(o+0x0e + slot*2,(uint16_t)c[category?15:14]);}
  unsigned shape=src_shape(ram,p);src_w16(o+0xa+slot*2,src_special(ram,p)?c[20]:shape_icon[shape]);
  src_w32(o+0x14+slot*4,src_r32(ram+c[5]+shape*4));src_w32(o+0x1c+slot*4,p?p+0x28:c[6]);
 }
 uint16_t value=src_r16(o+0xc);
 if(value==c[20]||value==shape_icon[0]||value==shape_icon[1]||value==shape_icon[2]||value==shape_icon[3])src_w16(o+0xc,(uint16_t)(value+1));
 value=src_r16(o+4);
 for(unsigned i=0;i<4;i++)if(value==category_icon[i]){src_w16(o+4,(uint16_t)(value+4));break;}
 native_font_preset_model(ram+c[1],ram+c[2],c[7],ram+c[3]);
 uint32_t result=0;
 for(unsigned i=0;i<2;i++){result=(uint32_t)native_measure_model((FontState*)(ram+c[1]),ram+src_r32(o+0x1c+i*4),0);src_w16(o+0x24+i*2,(uint16_t)result);}
 return result;
}
