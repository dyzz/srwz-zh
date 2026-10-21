/* Pure reconstruction of signed-number wrapper scheduling and coordinates.
 * Leaves (main text parser, numeric producer, packet builder) are verified
 * separately. Negative INT32_MIN uses native 32-bit wrap, no C signed UB.
 */
#include <stdint.h>
/* result: has_minus, minus_x, minus_y, numeric_value, numeric_x,
 * numeric_y, right, minus_chain (native always zero). */
void native_signed_numeric_plan(int32_t value,int16_t x,int16_t y,int right,
 int16_t number_advance,int16_t class_b_advance,int32_t *out){
 out[0]=value<0;out[1]=x;out[2]=y;out[3]=value;out[4]=x;out[5]=y;out[6]=right;out[7]=0;
 if(value>=0)return;
 int32_t magnitude=(int32_t)(0u-(uint32_t)value);out[3]=magnitude;
 if(right){
  unsigned digits=0;int32_t n=magnitude;
  do{digits++;n/=10;}while(n);
  out[1]=(int16_t)((int32_t)x-(int32_t)digits*number_advance-class_b_advance);
 }else out[4]=(int16_t)((int32_t)x+number_advance);
}
