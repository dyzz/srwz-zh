/* Name-confirmation: trim only trailing two-byte 0x8140 cells, modify input
 * in place, copy to three substitution buffers, set completion/selection bytes.
 * The capacity failures below are analysis guards absent from native code.
 */
#include <stdint.h>
#include <string.h>
int native_name_writer_model(uint8_t *object,uint8_t *a,uint8_t *b,uint8_t *c,uint8_t *globals,unsigned capacity){
 uint8_t *fields[3]={a,b,c};const unsigned targets[3]={12,29,1};
 for(unsigned field=0;field<3;field++){
  uint8_t *p=fields[field]+8;int count=(int8_t)fields[field][0x42],last=0;
  for(int i=0;i<count;i++){
   if(!p[i*2])break;
   if(p[i*2]!=0x81||p[i*2+1]!=0x40)last=i+1;
  }
  p[last*2]=0;
  size_t n=strlen((const char*)p)+1;if(targets[field]+n>capacity)return -1;
  memcpy(globals+targets[field],p,n);
 }
 object[7]=1;globals[0]=object[0xa];return 0;
}
