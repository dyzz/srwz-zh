/* Analysis-only candidate entry. Stock native_parse_model keeps flags=0. */
#include "parse_model.c"
int native_parse_optical_model(uint8_t *f,uint8_t *records,uint16_t *pending,
 unsigned *pending_count,const uint8_t *input,const uint8_t *extended,
 const uint8_t *const substitutions[4],uint32_t z_arg,unsigned record_slots,unsigned pending_slots){
 return native_parse_model_impl(f,records,pending,pending_count,input,extended,substitutions,z_arg,record_slots,pending_slots,3);
}
