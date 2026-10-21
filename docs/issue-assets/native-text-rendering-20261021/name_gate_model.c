/* Generic name-field validation block followed by virtual slot +0x98.
 * Complete confirmation writer model included for this concrete vtable.
 * Null field pointers / counts outside 0..3 are outside this model domain.
 */
#include "name_writer_model.c"
int native_name_gate_model(uint8_t *object,uint8_t *a,uint8_t *b,uint8_t *c,uint8_t *globals,unsigned capacity,int16_t count,int32_t *event){
 if(count<0||count>3)return -1;
 uint8_t *fields[3]={a,b,c};int valid=1;
 for(int i=0;i<count;i++){
  const uint8_t *p=fields[i]+8;int16_t n=(int16_t)(strlen((const char*)p)/2),blank=0;
  for(int j=0;j<n;j++){
   if(!p[j*2])break;
   if(p[j*2]==0x81&&p[j*2+1]==0x40)blank++;
  }
  valid=valid&&(blank<n);
 }
 if(valid){if(native_name_writer_model(object,a,b,c,globals,capacity))return -1;return 1;}
 *event=6;return 0;
}
