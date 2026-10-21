/* Reconstructed font resource decode wrapper 1C6C40 and body 1C6D70.
 * Header integers/record logic mirror native instructions. Input/capacity
 * checks (-1) are analysis bounds absent from the original code.
 * The wrapper returns declared size even when the body reports a bad match.
 */
#include <stdint.h>
#include <stddef.h>
static int rdint(const uint8_t *src,size_t size,size_t *p,uint32_t seed,uint32_t *value){
 uint32_t x=seed;
 for(unsigned guard=0;guard<16;guard++){
  if(*p>=size)return -1;
  uint8_t b=src[(*p)++];x=(x<<7)|b;
  if(x&1){*value=x>>1;return 0;}
 }
 return -1;
}
int32_t native_font_decode_model(const uint8_t *src,size_t size,uint8_t *out,size_t capacity,
 size_t *consumed,size_t *written,int *body_error){
 size_t p=0,n=0;uint32_t declared,flags,ignored;*body_error=0;
 if(rdint(src,size,&p,0,&declared))return -1;
 if(!declared){*consumed=p;*written=0;return 0;}
 if(rdint(src,size,&p,0,&flags))return -1;
 uint32_t window=1u<<(((flags>>1)&15)+8);
 if((window<declared||(flags&0x21)!=1)&&(flags&0x40))if(rdint(src,size,&p,0,&ignored))return -1;
 if(rdint(src,size,&p,0,&ignored))return -1;
 while(n<declared){
  if(p>=size)return -1;
  unsigned header=src[p++];uint32_t literals=header&15,matches=header>>4;
  if(!literals&&rdint(src,size,&p,0,&literals))return -1;
  if(!matches&&rdint(src,size,&p,0,&matches))return -1;
  if(!literals||p+literals>size||n+literals>capacity)return -1;
  while(literals--)out[n++]=src[p++];
  if(n>=declared)break;
  if(!matches)return -1;
  while(matches--){
   if(p>=size)return -1;
   unsigned token=src[p++];uint32_t low=token&15,len=token>>4;
   if(!(low&1)){if(rdint(src,size,&p,low,&low))return -1;}else low>>=1;
   if(!len&&rdint(src,size,&p,0,&len))return -1;
   uint32_t distance=low+1;len++;
   if(distance>n){*body_error=1;goto done;}
   if(len>declared-n)len=(uint32_t)(declared-n);
   if(n+len>capacity)return -1;
   while(len--){out[n]=out[n-distance];n++;}
   if(n>=declared)goto done;
  }
 }
 done:*consumed=p;*written=n;return (int32_t)declared;
}
