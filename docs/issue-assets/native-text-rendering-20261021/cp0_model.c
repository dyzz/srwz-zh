/* Native IRQ wrapper integer semantics plus declared LRPS2 CP0 adapter model.
 * A negative enter result denotes stable-status nontermination, not native
 * error return. Event-clock fields do not simulate interrupt delivery.
 */
#include <stdint.h>
static int cp_allowed(uint32_t status){return (status&0x20006u)||(status&0x18u)==0;}
int native_irq_enter_model(uint32_t *status){
 if(!(*status&0x10000u))return 0;
 if(!cp_allowed(*status))return -1;
 *status&=0xfffeffffu;return 1;
}
uint32_t native_irq_exit_model(uint32_t *status,uint64_t cycle,uint64_t *next){
 uint32_t previous=(*status>>16)&1;
 if(cp_allowed(*status)){
  *status|=0x10000u;
  if((int32_t)(uint32_t)(*next-cycle)>4)*next=cycle+4;
 }
 return previous;
}
