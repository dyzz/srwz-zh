/* Native byte scanning, no awareness of SJIS parity or control parameters. */
#include <stdint.h>
#include <string.h>
int native_count_below_limit_model(const uint8_t *text,int32_t limit,uint8_t delimiter){
 if(!text||!*text||limit<=0)return 0;
 int count=0;const uint8_t *end=text+strlen((const char*)text),*p=text;
 do{
  while(p!=end&&*p!=delimiter)p++;
  if(p==end)return count+1;
  count++;p++;
 }while(count<limit);
 return 0;
}
int native_select_byte_line_model(const uint8_t *text,int32_t index,uint32_t *offset,uint32_t *length,uint8_t delimiter){
 if(!text)return 0;*offset=0;*length=0;
 const uint8_t *base=text,*end=text+strlen((const char*)text),*p=text;
 for(int budget=254;budget>=0;budget--){
  while(p!=end&&*p!=delimiter)p++;
  if(index==0){*length=(uint32_t)(p-base);return *length>0;}
  int32_t next=(int32_t)((uint32_t)index-1u);
  if(p==end||next<0)return 0;
  index=next;*offset+=(uint32_t)(p-base)+1;base=++p;
 }
 return 0;
}
