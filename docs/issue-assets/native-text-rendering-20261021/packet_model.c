/* Byte reconstruction of native 13ACA0..13BD60, no graphics API used.
 * Parameters correspond to primary 32-byte records and secondary 32-byte
 * numeric/symbol records. Templates are read from each native executable.
 * Copying byte constants preserves packet formats without inventing labels.
 */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
static uint16_t pk_u16(const uint8_t*p){return p[0]|((uint16_t)p[1]<<8);}
static int16_t pk_s16(const uint8_t*p){return (int16_t)pk_u16(p);}
static uint32_t pk_u32(const uint8_t*p){return pk_u16(p)|((uint32_t)pk_u16(p+2)<<16);}
static uint64_t pk_u64(const uint8_t*p){return pk_u32(p)|((uint64_t)pk_u32(p+4)<<32);}
static void pk_w16(uint8_t*p,uint16_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);}
static void pk_w32(uint8_t*p,uint32_t v){pk_w16(p,(uint16_t)v);pk_w16(p+2,(uint16_t)(v>>16));}
static void pk_w64(uint8_t*p,uint64_t v){pk_w32(p,(uint32_t)v);pk_w32(p+4,(uint32_t)(v>>32));}
static uint64_t pk_uv(int16_t u,int16_t v){return ((uint64_t)(int64_t)u<<4)|((uint64_t)(int64_t)v<<20);}
static uint64_t pk_xyz(int32_t x,int16_t y,uint32_t z){return ((uint64_t)(int64_t)x<<4)|((uint64_t)(int64_t)y<<20)|((uint64_t)z<<32);}
/* Returns native alias pointer; written includes all bytes stored in buffer.
 * capacity failures return 0, a harness bound absent from native code. */
uint32_t native_packet_model(uint8_t *out,size_t capacity,uint32_t input_addr,int chain,
 const uint8_t *primary,unsigned primary_count,const uint8_t *secondary,unsigned secondary_count,
 int16_t offset_x,int16_t offset_y,const uint8_t *templates,size_t *written){
 *written=0;if(!primary_count&&!secondary_count)return input_addr;
 if(capacity<128)return 0;
 const int order[8]={0x50,0,0x10,0x20,0x60,0x30,0x70,0x40};
 for(int i=0;i<8;i++)memcpy(out+i*16,templates+order[i],16);
 size_t p=chain?96:128;
 if(chain)pk_w32(out,(pk_u32(out)&0xffff8000u)|5u);
 for(int type=0;type<2;type++){
  unsigned count=type?secondary_count:primary_count;const uint8_t *records=type?secondary:primary;
  for(unsigned i=0;i<count;i++){
   const uint8_t *r=records+i*32;unsigned shear=r[type?0x10:0x12],palette=r[type?0xe:0x10],page=r[type?0xf:0x11];
   size_t stride=shear?112:80;int outline=r[0x1c]!=0;size_t begin=p,center=p+(outline?8*stride:0);
   if(center+stride>capacity)return 0;
   uint8_t *q=out+center;memcpy(q,templates+(shear?0x80:0x90),16);memcpy(q+16,templates+(shear?0xa0:0xa8),8);
   pk_w64(q+24,pk_u64(templates+0xc0)|((uint64_t)page<<20)|((uint64_t)palette<<56));
   pk_w64(q+32,pk_u32(r+0x14));
   int16_t u=(int16_t)(pk_s16(r)+1),v=(int16_t)(pk_s16(r+2)+1),ur=(int16_t)(u+23),vb=(int16_t)(v+23);
   int16_t x=(int16_t)(offset_x+pk_s16(r+4)),y=(int16_t)(offset_y+pk_s16(r+6));
   int16_t width=type?r[0xc]:pk_s16(r+0xc),height=type?r[0xd]:pk_s16(r+0xe);
   int16_t xr=(int16_t)(x+width),yb=(int16_t)(y+height);uint32_t z=pk_u32(r+8);
   if(shear){
    pk_w64(q+40,pk_uv(u,v));pk_w64(q+48,pk_xyz((int32_t)x+(int32_t)shear,y,z));
    pk_w64(q+56,pk_uv(ur,v));pk_w64(q+64,pk_xyz((int32_t)xr+(int32_t)shear,y,z));
    pk_w64(q+72,pk_uv(u,vb));pk_w64(q+80,pk_xyz(x,yb,z));
    pk_w64(q+88,pk_uv(ur,vb));pk_w64(q+96,pk_xyz(xr,yb,z));
   }else{
    pk_w64(q+40,pk_uv(u,v));pk_w64(q+48,pk_xyz(x,y,z));
    pk_w64(q+56,pk_uv(ur,vb));pk_w64(q+64,pk_xyz(xr,yb,z));
   }
   if(outline){
    uint32_t saved=pk_u32(q+32);pk_w32(q+32,pk_u32(r+0x18));
    for(int n=0;n<8;n++)memcpy(out+begin+n*stride,q,stride);
    pk_w32(q+32,saved);
    const int dx[8]={-16,0,16,-16,16,-16,0,16};const int dy[8]={-8,-8,-8,0,0,8,8,8};
    for(int n=0;n<8;n++)for(int k=0;k<(shear?4:2);k++){
     uint8_t *xy=out+begin+n*stride+48+k*16;
     pk_w16(xy,(uint16_t)(pk_s16(xy)+dx[n]));pk_w16(xy+2,(uint16_t)(pk_s16(xy+2)+dy[n]));
    }
   }
   p=center+stride;
  }
 }
 uint32_t physical=input_addr&0x0fffffffu;unsigned pad=(~((physical+(uint32_t)p)>>4)&3u)+1u;
 if(p+pad*16>capacity)return 0;
 for(unsigned i=0;i<pad;i++){memcpy(out+p,templates+0xb0,16);p+=16;}
 *written=p;return (physical+(uint32_t)p)|0x30000000u;
}
