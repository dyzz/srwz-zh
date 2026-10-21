/* Selector2 lookup + coordinate helper + complete 5039 dispatch for selectors
 * 0/2 and direct (<8000) IDs. Selector1/3, special IDs and multi-target80 remain
 * unimplemented requirements, not silently mapped to this branch.
 * COP1 comparison scope: finite binary32 operations, not general EE FPU flags.
 */
#include "measure_owner_model.c"
static void lookup_coordinate(uint8_t*ram,uint32_t entity,const uint32_t*c){
 if((int8_t)ram[entity+0x6c]<0)ram[entity+0x6c]=0;
 if((int8_t)ram[entity+0x6d]<0)ram[entity+0x6d]=0;
 unsigned x=ram[entity+0x6c],y=ram[entity+0x6d];uint32_t grid=src_r32(ram+c[1]);
 float px=0.5f*(float)x,pz=-0.5f*(float)y,epsilon;uint32_t bits=0x3ac49ba6;memcpy(&epsilon,&bits,4);
 float height=0.25f*(float)(int8_t)ram[grid+y*352u+x*8u];float py=height-epsilon;
 memcpy(ram+entity+0x50,&px,4);memcpy(ram+entity+0x54,&py,4);memcpy(ram+entity+0x58,&pz,4);
}
void native_name_lookup_coordinate_model(uint8_t*ram,uint32_t entity,const uint32_t*c){lookup_coordinate(ram,entity,c);}
int32_t native_selector2_lookup_model(uint8_t*ram,const uint32_t*c,int32_t id,int32_t side,uint32_t flags,uint32_t context){
 if(context){src_w32(ram+context+0x2f90,0);src_w32(ram+context+0x2f94,0);src_w32(ram+context+0x2f98,0);}
 for(unsigned row=0;row<120;row++){
  uint32_t entity=c[0]+row*176u;
  if(!(ram[entity+0x14]&3))continue;
  if(side>=0&&side!=ram[entity+0x25])continue;
  if((flags&2)&&!ram[entity+0x24])continue;
  if(!(flags&8)&&(ram[entity+0x16]&64))continue;
  for(unsigned member=0;member<3;member++){
   uint32_t unit=src_r32(ram+entity+8+member*4);if(!unit)continue;
   for(unsigned slot=0;slot<6;slot++){
    uint32_t pilot=src_r32(ram+unit+0xb0+slot*4);if(!pilot)continue;
    uint32_t definition=src_r32(ram+pilot);if((int32_t)src_r16(ram+definition)!=id)continue;
    if((flags&4)&&(ram[pilot+0x40]&1))continue;
    uint32_t unit_def=src_r32(ram+unit+0xa8);int16_t parent=(int16_t)src_r16(ram+entity+0x68);
    if(!(ram[unit_def+0x30]&4)&&parent>=0){
     uint32_t p=c[0]+(uint32_t)(int32_t)parent*176u;ram[entity+0x6c]=ram[p+0x6c];ram[entity+0x6d]=ram[p+0x6d];lookup_coordinate(ram,entity,c);
    }
    if(context){src_w32(ram+context+0x2f90,entity);src_w32(ram+context+0x2f94,pilot);src_w32(ram+context+0x2f98,unit);}
    return (int32_t)row;
   }
  }
 }
 return -1;
}
int32_t native_selector02_wrapper_model(uint8_t*ram,const uint32_t*c,int32_t mode,int32_t id,uint32_t options,uint32_t context){
 /* Native compares (options&100) to1, so that branch never sets bit2. */
 if(mode!=0&&mode!=2)return (int32_t)0xdead0002;
 uint32_t flags=options&13u;
 return native_selector2_lookup_model(ram,c,id,-1,flags,context);
}
uint32_t native_name5039_selector2_model(uint8_t*ram,const uint32_t*c,uint32_t command,uint32_t context){
 uint32_t argument=src_r32(ram+command+4),mode=argument>>16,id=argument&65535;
 if((mode!=0&&mode!=2)||id>=0x8000)return 0xdead5039; /* outside declared branch */
 int32_t row=native_selector02_wrapper_model(ram,c,(int32_t)mode,(int32_t)id,0,context);
 if(row<0||!src_r32(ram+context+0x2f90))return 0;
 native_name_command_tail_model(ram,c[0],(uint32_t)row,command);return 1;
}
