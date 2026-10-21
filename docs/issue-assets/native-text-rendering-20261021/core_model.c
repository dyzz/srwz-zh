/* Reconstructed native integer semantics, Original VA comments.
 * Covers measurement, classified metric selection and glyph resolution.
 * parse_model.c reconstructs the record-building path. Neither emits graphics.
 * Exact offsets are asserted; incomplete fields retain neutral names.
 */
#include <stdint.h>
#include <stddef.h>
typedef struct {
    uint8_t opaque_00[0x14];
    int16_t width, height, advance_x, advance_y; /* +14..1A */
    uint8_t opaque_1c[0x1c];
    int16_t a_width, a_height, a_advance_x, a_advance_y; /* +38 */
    int16_t b_width, b_height, b_advance_x, b_advance_y; /* +40 */
    int16_t classified;
    uint8_t attribute_4a;
    int8_t upper, lower, hira, kata, broad; /* +4B..4F */
} FontState;
_Static_assert(offsetof(FontState,width)==0x14,"explicit width offset");
_Static_assert(offsetof(FontState,a_width)==0x38,"A metrics offset");
_Static_assert(offsetof(FontState,classified)==0x48,"mode offset");
_Static_assert(offsetof(FontState,broad)==0x4f,"last classification flag");
/* Native 139B00. Caller must supply the native NUL-terminated byte stream.
 * No newline, height, 0x35 or substitution support is added here.
 * Width and space controls mutate shared state; this function does NOT restore it.
 */
int32_t native_measure_model(FontState *f, const uint8_t *p, int full_width) {
    uint32_t total=0;
    const int16_t ax=f->a_advance_x, bx=f->b_advance_x;
    const int upper=f->upper,lower=f->lower,hira=f->hira,kata=f->kata,broad=f->broad;
    while (*p) {
        if (*p==0x31) { p+=2; continue; }
        if (*p==0x32) { f->width=p[1]; f->classified=0; p+=2; continue; }
        if (*p==0x34) { f->advance_x=p[1]; f->classified=0; p+=2; continue; }
        uint16_t c=(uint16_t)((p[0]<<8)|p[1]); p+=2;
        int use_b=0;
        if (!f->classified) { total+=(uint32_t)(int32_t)f->advance_x; continue; }
        if      (c>=0x8260 && c<0x827a) use_b=upper!=0;
        else if (c>=0x8281 && c<0x829b) use_b=lower!=0;
        else if (c>=0x829f && c<0x82f2) use_b=hira!=0;
        else if (c>=0x8340 && c<0x8492) use_b=kata!=0;
        else if (c>=0x8140 && c<0x889f) use_b=broad!=0;
        total+=(uint32_t)(int32_t)(use_b?bx:ax);
    }
    int32_t sum=(int32_t)total;
    return full_width ? sum : -(sum/2);
}
/* Native 13A630..13A79C. Range order differs from native_measure_model.
 * Broad flag has priority for [8140,829F), then kata, upper, hira, lower.
 */
int native_draw_uses_b(const FontState *f,uint16_t c) {
    if (c>=0x8492) return 0;
    if (f->broad && c>=0x8140 && c<0x829f) return 1;
    if (f->kata && c>=0x8340 && c<0x8492) return 1;
    if (f->upper && c>=0x8260 && c<0x827a) return 1;
    if (f->hira && c>=0x829f && c<0x82f2) return 1;
    if (f->lower && c>=0x8281 && c<0x829b) return 1;
    return 0;
}
/* Native 13A7A0..13A990, including unchecked trail bytes and uint16 wrap.
 * Table records are {code_le16, signed_row, packed_position}, NUL terminated.
 * This function does not impose the authoring tools' valid-slot restrictions.
 */
uint16_t native_glyph_resolve_model(uint16_t code,const uint8_t *table) {
    switch(code>>8) {
    case 0x81:return (uint16_t)(code-0x8140);
    case 0x82:return (uint16_t)(code-0x8180);
    case 0x83:return (uint16_t)(code-0x81c0);
    case 0x84:return (uint16_t)(code-0x8200);
    case 0x87:return (uint16_t)(code-0x82c0);
    case 0x88:return (uint16_t)(code-0x8300);
    default:break;
    }
    if(code>=0x989f) {
        for(;;table+=4) {
            uint16_t key=(uint16_t)(table[0]|(table[1]<<8));
            if(!key)return 0;
            if(key==code)return (uint16_t)((int8_t)table[2]*224+table[3]);
        }
    }
    return (uint16_t)(((int)(code>>8)-0x89)*192+0x5c0+(code&255));
}
