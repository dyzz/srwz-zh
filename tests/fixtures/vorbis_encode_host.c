/* stdin: 48 kHz stereo s16le PCM -> stdout: Ogg Vorbis, libvorbis VBR quality 0
 * (the setting the /music/ page uses). Test fixture for test_vocal_stream.py. */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <vorbis/vorbisenc.h>

static void flush_pages(ogg_stream_state *os, int force){
  ogg_page og;
  while(force?ogg_stream_flush(os,&og):ogg_stream_pageout(os,&og)){
    fwrite(og.header,1,og.header_len,stdout);fwrite(og.body,1,og.body_len,stdout);
  }
}

int main(void){
  vorbis_info vi;vorbis_comment vc;vorbis_dsp_state vd;vorbis_block vb;ogg_stream_state os;
  vorbis_info_init(&vi);
  if(vorbis_encode_init_vbr(&vi,2,48000,0.0f))return 1;
  vorbis_comment_init(&vc);vorbis_analysis_init(&vd,&vi);vorbis_block_init(&vd,&vb);
  ogg_stream_init(&os,12345);
  ogg_packet h,hc,hb;vorbis_analysis_headerout(&vd,&vc,&h,&hc,&hb);
  ogg_stream_packetin(&os,&h);ogg_stream_packetin(&os,&hc);ogg_stream_packetin(&os,&hb);flush_pages(&os,1);
  short in[4096*2];size_t n;
  while((n=fread(in,4,4096,stdin))>0){
    float **buf=vorbis_analysis_buffer(&vd,(int)n);
    for(size_t i=0;i<n;i++){buf[0][i]=in[2*i]/32768.f;buf[1][i]=in[2*i+1]/32768.f;}
    vorbis_analysis_wrote(&vd,(int)n);
    while(vorbis_analysis_blockout(&vd,&vb)==1){
      vorbis_analysis(&vb,NULL);vorbis_bitrate_addblock(&vb);ogg_packet op;
      while(vorbis_bitrate_flushpacket(&vd,&op)){ogg_stream_packetin(&os,&op);flush_pages(&os,0);}
    }
  }
  vorbis_analysis_wrote(&vd,0);
  while(vorbis_analysis_blockout(&vd,&vb)==1){
    vorbis_analysis(&vb,NULL);vorbis_bitrate_addblock(&vb);ogg_packet op;
    while(vorbis_bitrate_flushpacket(&vd,&op)){ogg_stream_packetin(&os,&op);flush_pages(&os,0);}
  }
  flush_pages(&os,1);
  return 0;
}
