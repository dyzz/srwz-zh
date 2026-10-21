/* Native deferred reference-chain + host-to-local image packet construction.
 * No DMA/GS execution. Capacity checks belong only to this analysis model.
 * g: current_data, previous_reference_end, chain_write_pointer.
 */
#include <stdint.h>
#include <stddef.h>
static uint64_t tx_s32(uint32_t v){return (uint64_t)(int64_t)(int32_t)v;}
static void tx_w64(uint8_t *p,uint64_t v){for(unsigned i=0;i<8;i++)p[i]=(uint8_t)(v>>(8*i));}
static int tx_append(uint32_t *g,uint8_t *chain,size_t size,uint32_t base,uint64_t tag){
 uint32_t offset=g[2]-base;if(offset>size||size-offset<8)return -1;
 tx_w64(chain+offset,tag);g[2]+=16;return 0;
}
int native_transfer_flush_model(uint32_t *g,uint8_t *chain,size_t size,uint32_t base,uint32_t current){
 uint32_t previous=g[1];g[0]=current;
 int32_t difference=(int32_t)(current-previous),qwc=difference/16;
 if(!qwc)return 0;
 uint64_t tag=(tx_s32((uint32_t)qwc)|UINT64_C(0x30000000))|((uint64_t)(previous&0x0ffffff0u)<<32);
 if(tx_append(g,chain,size,base,tag))return -1;
 g[1]=current;return 0;
}
uint32_t native_transfer_builder_model(uint32_t *g,uint8_t *chain,size_t chain_size,uint32_t chain_base,
 uint8_t *packet,size_t packet_size,uint32_t packet_address,const uint32_t *p){
 /* p: DBP,DBW,DPSM,source_address,QWC,destinationX,Y,transferW,H. */
 if(packet_size<112||native_transfer_flush_model(g,chain,chain_size,chain_base,packet_address))return 0;
 uint64_t descriptor_ref=((uint64_t)(packet_address&0x0ffffff0u)<<32)|UINT64_C(0x30000007);
 if(tx_append(g,chain,chain_size,chain_base,descriptor_ref))return 0;
 tx_w64(packet,UINT64_C(0x1000000000000005));tx_w64(packet+8,14);
 tx_w64(packet+16,0);tx_w64(packet+24,0x3f);
 tx_w64(packet+32,(tx_s32(p[0])<<32)|(tx_s32(p[1])<<48)|(tx_s32(p[2])<<56));tx_w64(packet+40,0x50);
 tx_w64(packet+48,(tx_s32(p[5])<<32)|(tx_s32(p[6])<<48));tx_w64(packet+56,0x51);
 tx_w64(packet+64,tx_s32(p[7])|(tx_s32(p[8])<<32));tx_w64(packet+72,0x52);
 tx_w64(packet+80,0);tx_w64(packet+88,0x53);
 tx_w64(packet+96,tx_s32(p[4])|UINT64_C(0x0800000000008000));tx_w64(packet+104,0);
 uint64_t image_ref=((uint64_t)(p[3]&0xfffffff0u)<<32)|(tx_s32(p[4])|UINT64_C(0x30000000));
 if(tx_append(g,chain,chain_size,chain_base,image_ref))return 0;
 g[1]=packet_address+112;return packet_address+112;
}
/* Reconstructed dirty-gated two-half font-atlas scheduling block.
 * The containing frame function's live registers and eventual DMA call are
 * outside this block. Native current/previous packet pointers are restored.
 */
int native_font_upload_pair_model(uint32_t *g,uint8_t *chain,size_t chain_size,uint32_t chain_base,
 uint8_t *packet,size_t packet_size,uint32_t packet_base,uint32_t *dirty,
 uint32_t atlas,uint32_t *temporary,uint32_t *chain_origin){
 if(!*dirty)return 0;
 uint32_t saved_current=g[0],saved_previous=g[1];*dirty=0;
 g[2]=chain_base;*chain_origin=chain_base;g[0]=packet_base;g[1]=packet_base;*temporary=atlas;
 uint32_t p[9]={0x1180,8,0x24,atlas,0xf00,0,0,512,240};
 uint32_t result=native_transfer_builder_model(g,chain,chain_size,chain_base,packet,packet_size,packet_base,p);
 if(!result)return -1;
 g[0]=result;*temporary=atlas+0xf000u;p[2]=0x2c;p[3]=*temporary;
 size_t offset=result-packet_base;if(offset>packet_size)return -1;
 result=native_transfer_builder_model(g,chain,chain_size,chain_base,packet+offset,packet_size-offset,result,p);
 if(!result)return -1;
 g[0]=saved_current;g[1]=saved_previous;return 0;
}
