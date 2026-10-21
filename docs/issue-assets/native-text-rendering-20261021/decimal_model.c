/* Observed native atoi contract: base-ten signed 64-bit strtol semantics,
 * then truncate/sign-extend to int32. ASCII inputs only. errno and endptr
 * effects intentionally outside this value model and verified scope.
 */
#include <stdint.h>
int32_t native_decimal_value_model(const uint8_t *p){
 while(*p==' '||(*p>=9&&*p<=13))p++;
 int negative=0;if(*p=='+'||*p=='-'){negative=*p=='-';p++;}
 uint64_t limit=negative?UINT64_C(0x8000000000000000):UINT64_C(0x7fffffffffffffff),value=0;int overflow=0;
 while(*p>='0'&&*p<='9'){
  unsigned digit=*p++-'0';if(value>limit/10||(value==limit/10&&digit>limit%10))overflow=1;
  if(!overflow)value=value*10+digit;
 }
 if(overflow)value=limit;
 uint64_t result=negative?(uint64_t)0-value:value;
 return (int32_t)(uint32_t)result;
}
