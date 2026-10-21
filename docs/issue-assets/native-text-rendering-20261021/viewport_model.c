/* Library viewport state; no pagination hidden in these methods. */
#include "split_model.c"
static uint32_t vp_r32(const uint8_t *p){return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void vp_w32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(i*8));}
void native_viewport_setup_model(uint8_t *object,uint32_t text,uint32_t descriptor,int64_t visible,const uint8_t *arrows){
 vp_w32(object+4,text);vp_w32(object+12,(uint32_t)visible);vp_w32(object+16,descriptor);memcpy(object+20,arrows,6);vp_w32(object+8,0);
}
int native_viewport_can_down_model(const uint8_t *object,const uint8_t *text){
 int count=native_count_below_limit_model(text,255,10);
 int32_t remaining=(int32_t)((uint32_t)count-vp_r32(object+8));return (int32_t)vp_r32(object+12)<remaining;
}
int native_viewport_down_model(uint8_t *object,const uint8_t *text){
 int yes=native_viewport_can_down_model(object,text);if(yes)vp_w32(object+8,vp_r32(object+8)+1u);return yes;
}
void native_viewport_up_model(uint8_t *object){
 uint32_t top=vp_r32(object+8);if((int32_t)top>0)vp_w32(object+8,top-1u);
}
