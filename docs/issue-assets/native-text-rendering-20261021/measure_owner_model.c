/* Context primary setter, selected-entry iterator/reset, and a real caller
 * window's iterator -> getter -> whole presentation initializer composition.
 * The secondary setter's selection services are outside this model.
 */
#include "measure_source_model.c"
uint32_t native_primary_source_set_model(uint8_t*ram,const uint32_t*c,uint32_t entity,uint64_t flag){
 if(!entity)return 0xffffffffu;
 uint32_t member=src_r32(ram+entity+8);src_w32(ram+c[0]+4,entity);src_w16(ram+c[0]+12,0);src_w32(ram+c[0]+8,member);ram[c[0]]=(uint8_t)(flag!=0);
 src_w32(ram+c[7],entity);src_w32(ram+c[8],member);return 1;
}
void native_owner_reset_model(uint8_t*ram,const uint32_t*c){src_w32(ram+c[1],0);}
uint32_t native_owner_next_model(uint8_t*ram,const uint32_t*c){
 int32_t i=(int32_t)src_r32(ram+c[1]),limit=(int32_t)src_r32(ram+c[2]);src_w32(ram+c[3],(uint32_t)i);
 if(i>=limit)return 0;
 uint32_t slot=c[6]+(uint32_t)i*12u;uint32_t node=src_r32(ram+slot);src_w32(ram+c[1],(uint32_t)i+1u);
 if(!node)return 0;
 node=src_r32(ram+node+8);uint32_t entity=src_r32(ram+node+8);
 src_w32(ram+c[4],entity);src_w32(ram+c[5],entity);return 1;
}
uint32_t native_owner_presentation_step_model(uint8_t*ram,const uint32_t*owner,const uint32_t*source,const uint32_t*failure){
 if(!native_owner_next_model(ram,owner)){
  uint32_t address=failure[1]?src_r32(ram+failure[0]):failure[0];
  if(failure[2]==1)ram[address]=20;else src_w16(ram+address,20);
  return 0;
 }
 native_two_entity_cache_model(ram,src_r32(ram+owner[0]+4),src_r32(ram+owner[4]),source);return 1;
}

/* Native opcode5039 resolved-index copy tail; does not model the index resolver. */
uint32_t native_name_command_tail_model(uint8_t*ram,uint32_t table,uint32_t index,uint32_t command){
 uint32_t dst=table+index*176u+40u,src=src_r32(ram+command+8),p=dst;
 uint8_t byte;do{byte=ram[src++];ram[p++]=byte;}while(byte);
 return dst;
}
