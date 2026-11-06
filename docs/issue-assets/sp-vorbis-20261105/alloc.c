#include <stdint.h>
#include <stddef.h>
#include <string.h>
extern volatile uint32_t result[12];
void *__real_malloc(size_t);
void __real_free(void*);
static size_t live;
typedef struct {size_t n;uint32_t tracked;uint32_t pad[2];} Header;
void *__wrap_malloc(size_t n){
 if(n>(size_t)-1-sizeof(Header))return 0;
 Header *h=__real_malloc(n+sizeof(Header));if(!h)return 0;
 h->n=n;h->tracked=result[1]==1||result[1]==2;
 if(h->tracked){live+=n;result[10]=live;if(live>result[9])result[9]=live;if(n>result[11])result[11]=n;}
 return h+1;
}
void __wrap_free(void *p){if(!p)return;Header*h=(Header*)p-1;if(h->tracked){live-=h->n;result[10]=live;}__real_free(h);}
void *__wrap_calloc(size_t n,size_t s){if(s&&n>(size_t)-1/s)return 0;void*p=__wrap_malloc(n*s);if(p)memset(p,0,n*s);return p;}
void *__wrap_realloc(void*p,size_t n){if(!p)return __wrap_malloc(n);if(!n){__wrap_free(p);return 0;}Header*h=(Header*)p-1;void*q=__wrap_malloc(n);if(q){memcpy(q,p,h->n<n?h->n:n);__wrap_free(p);}return q;}
