/* Upper setter: signed-byte index, 22-byte row, class A/B plus number metrics.
 * Explicit geometry and text pen deliberately retain their prior values.
 */
#include <stdint.h>
#include <string.h>
void native_font_preset_model(uint8_t *state,const uint8_t *table,int64_t argument,uint8_t *last_preset){
 int index=(int8_t)argument;*last_preset=(uint8_t)argument;
 state[0x48]=1;state[0x49]=0;
 memcpy(state+0x38,table+index*22,16);memcpy(state+0x2c,table+index*22+16,6);
 memset(state+0x4b,1,5);
}
