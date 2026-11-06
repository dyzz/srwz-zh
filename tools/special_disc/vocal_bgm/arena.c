#include <stddef.h>
#include <string.h>
#include <stdint.h>
static unsigned char arena[524288] __attribute__((aligned(64)));
typedef struct Block {unsigned size,free;struct Block *next;unsigned pad;} Block;
static Block *head;
void arena_reset(void){head=(Block*)arena;head->size=sizeof(arena)-sizeof(Block);head->free=1;head->next=0;}
void *malloc(size_t n){n=(n+15)&~15;if(!head)arena_reset();for(Block *b=head;b;b=b->next)if(b->free&&b->size>=n){if(b->size>=n+sizeof(Block)+16){Block *v=(Block*)((char*)(b+1)+n);v->size=b->size-n-sizeof(Block);v->free=1;v->next=b->next;b->next=v;b->size=n;}b->free=0;return b+1;}return 0;}
void free(void *p){if(!p)return;Block*b=(Block*)p-1;b->free=1;for(b=head;b&&b->next;)if(b->free&&b->next->free){b->size+=sizeof(Block)+b->next->size;b->next=b->next->next;}else b=b->next;}
void *calloc(size_t n,size_t s){if(s&&n>SIZE_MAX/s)return 0;void*p=malloc(n*s);if(p)memset(p,0,n*s);return p;}
void *realloc(void*p,size_t n){if(!p)return malloc(n);if(!n){free(p);return 0;}Block*b=(Block*)p-1;if(b->size>=n)return p;void*q=malloc(n);if(q){memcpy(q,p,b->size);free(p);}return q;}
