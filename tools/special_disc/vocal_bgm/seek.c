/* Tremor's vorbisfile.c plus one entry point, ov_raw_pcm_seek.
 *
 * The player keeps only a window of the song in EE memory, so ov_pcm_seek's
 * page bisection (random reads over the whole file) cannot be served. The
 * player instead remembers a page boundary it passed some seconds before the
 * loop start and keeps the bytes from there. ov_raw_pcm_seek restarts decoding
 * at that page and then runs ov_pcm_seek's own tail: packets before the target
 * are only tracked, not decoded, and the last samples are discarded, so the
 * result is the same sample-exact position ov_pcm_seek reaches.
 *
 * This file is compiled instead of vorbisfile.c (it includes it) so the helper
 * can use the file's static functions. */
#include "vorbisfile.c"

int ov_raw_pcm_seek(OggVorbis_File *vf, ogg_int64_t raw, ogg_int64_t pos){
  int thisblock,lastblock=0;
  int ret=ov_raw_seek(vf,raw);
  if(ret<0)return(ret);
  /* The page must start at or before the target: never decode backwards. */
  if(vf->pcm_offset<0||vf->pcm_offset>pos)return(OV_EINVAL);
  if((ret=_make_decode_ready(vf)))return ret;

  /* From here on: ov_pcm_seek (vorbisfile.c), unchanged. */
  while(1){
    ogg_packet op;
    ogg_page og;

    int ret=ogg_stream_packetpeek(&vf->os,&op);
    if(ret>0){
      thisblock=vorbis_packet_blocksize(vf->vi+vf->current_link,&op);
      if(thisblock<0){
        ogg_stream_packetout(&vf->os,NULL);
        continue; /* non audio packet */
      }
      if(lastblock)vf->pcm_offset+=(lastblock+thisblock)>>2;

      if(vf->pcm_offset+((thisblock+
                          vorbis_info_blocksize(vf->vi,1))>>2)>=pos)break;

      ogg_stream_packetout(&vf->os,NULL);
      vorbis_synthesis_trackonly(&vf->vb,&op);
      vorbis_synthesis_blockin(&vf->vd,&vf->vb);

      if(op.granulepos>-1){
        int i;
        vf->pcm_offset=op.granulepos-vf->pcmlengths[vf->current_link*2];
        if(vf->pcm_offset<0)vf->pcm_offset=0;
        for(i=0;i<vf->current_link;i++)
          vf->pcm_offset+=vf->pcmlengths[i*2+1];
      }

      lastblock=thisblock;

    }else{
      if(ret<0 && ret!=OV_HOLE)break;

      if(_get_next_page(vf,&og,-1)<0)break;
      if(ogg_page_bos(&og))_decode_clear(vf);

      if(vf->ready_state<STREAMSET){
        ogg_uint32_t serialno=ogg_page_serialno(&og);
        int link;

        for(link=0;link<vf->links;link++)
          if(vf->serialnos[link]==serialno)break;
        if(link==vf->links) continue;
        vf->current_link=link;

        vf->ready_state=STREAMSET;
        vf->current_serialno=ogg_page_serialno(&og);
        ogg_stream_reset_serialno(&vf->os,serialno);
        ret=_make_decode_ready(vf);
        if(ret)return ret;
        lastblock=0;
      }

      ogg_stream_pagein(&vf->os,&og);
    }
  }

  vf->bittrack=0;
  vf->samptrack=0;
  while(vf->pcm_offset<pos){
    ogg_int64_t target=pos-vf->pcm_offset;
    long samples=vorbis_synthesis_pcmout(&vf->vd,NULL);

    if(samples>target)samples=target;
    vorbis_synthesis_read(&vf->vd,samples);
    vf->pcm_offset+=samples;

    if(samples<target)
      if(_fetch_and_process_packet(vf,NULL,1,1)<=0)
        return(OV_EINVAL); /* ran out of buffered bytes: never fake EOF */
  }
  return 0;
}
