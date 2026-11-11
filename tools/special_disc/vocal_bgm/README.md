# VOCAL.BIN player (SP / Z / The Best)

The browser music editor installs the player into its output ISO. SP (SLPS_259.20), Original (SLPS_258.87) and The Best (SLPS_732.70) have separate address profiles. Music Select and Battle Viewer share BGM IDs 0–100. Base release ISOs stay read-only; native tests use APFS clones under `build/iso/test`.

## Playback

Compressed 48 kHz stereo Ogg Vorbis is preloaded from `cdrom0:\BGM\VOCAL.BIN;1`, at most 4 MiB per track. The ELF embeds code and the PCM IRX, not the songs. Loading uses a separate nonblocking SIF RPC client, persistent request/reply buffers, 64 KiB reads and incremental CRC. The start callback queues work and returns; the update hook polls completion so the menu keeps updating during disc I/O. Metadata and the current validated compressed song are cached for replay. This remains whole-song preloading, not continuous streaming.

EE normal-precision Tremor decodes at most one PCM packet per update-hook call. The IOP sink queues 512-byte channel blocks using libsd DMA 1; DMA 0 stays available for native speech. Stop restores the previous DMA-1 interrupt handler. Cancelling a load drains its pending RPC and closes the file before another request reuses the buffers.

BGM.BIN remains unmodified. Missing entries and invalid metadata, bounds, CRC, Vorbis or frame count fall back to the already-loaded native score. Fallback guards the native start hook against reentry. Container v2 supports whole-track/range looping, one-shot playback and Q16 gain.

Known v1 browser player binaries can be upgraded in place: the installer checks their exact payload hashes and all hooks before updating the ELF. Existing songs and gain settings survive. Unknown binaries or changed hooks require a base ISO. Cold-boot the new ISO; an old emulator savestate retains old code.

Private EE range: `0x8c0000..0xdc0000`; both heap initialization and native break are adjusted. The gallery segment is preserved. Builds assert hook preimages, BGM hash, ELF capacity, payload bounds and unchanged bytes outside the explicit patch spans. ISO9660, VMAP and UDF all name the new file. Original source extents remain in place except relocated ELF and extended metadata.

## Container ABI

The browser runs the same `container.py` serializer through Pyodide.

- Capacity: 512 MiB shared across tracks; runtime IDs 0–100, 256 directory slots.
- Header: 2048 bytes, magic `SRWZVOC1`, version 1 / 2, profile `0x53500001` / `0x53500002`.
- Index: 256 slots × 64 bytes, at relative offset 2048; data starts at 18432.
- `<14I` at header byte 8: version, header size, index offset, entry size, slot count, data offset, used bytes, capacity, profile, index CRC32, header CRC32, flags 0, reserved 0, reserved 0. Header CRC is over all 2048 bytes with its own word (byte 48) zeroed.
- Entry `<16I`: track ID, active flag, relative byte offset, encoded byte length, sample rate, channels, PCM frames, loop start, loop end, gain, body CRC32, one-shot flag (v2), four reserved zeros.
- Track data is aligned to 2048 bytes. v1 accepts 48000 Hz, stereo, loop `[0, frames)`, gain `0..0x7fff` (default `0x4800`), encoded size at most 4 MiB. Empty entries contain their slot ID and all other fields zero.
- v2 gain is Q16, default 65536, up to 260904. Loop bounds satisfy `0 <= start < end <= frames`; the one-shot flag is 0 or 1. v1 retains its original native-volume semantics.
- Standard reflected CRC32, polynomial `0xedb88320`, initial/final XOR `0xffffffff`.

## Build

From `srwz-zh`, prepare the default nominal 64 kbit/s VBR preset (quality 0) without truncation:

```sh
ffmpeg -i /Users/nate/gba-sound/test.mp3 -ar 48000 -ac 2 -c:a libvorbis -q:a 0 /tmp/test-full64.ogg
python3 tools/special_disc/vocal_bgm/build_candidate.py \
  --ogg /tmp/test-full64.ogg \
  --toolchain work/analysis/vorbis-tremor-20261105/toolchain/ps2dev \
  --tremor-source /Users/nate/gba-sound/vorbis-preview-20261105/ps2-libtremor \
  --workdir work/analysis/sp-vocal-rebuild \
  --output-iso build/iso/test/sp-vocal-rebuild.iso
```

Use `--replace` only for an owned test image. `--payload-only` omits ISO construction. Input is 48 kHz stereo Vorbis, at most 4 MiB. Resampling does not increase source fidelity. Actual average VBR bitrate depends on the song.

Dependencies: native macOS arm64 ps2dev v2.0.0 toolchain, FFprobe, PS2SDK libogg, Tremor commit `ae62505aee8f4fc15cce97332133229ed8da0d5a`. GCC 15's legacy int*/long* warnings involve 32-bit EE types; compile uses `-fno-strict-aliasing`. Codec licenses are retained in `licenses/`.

## Browser tool and validation

Companion local page: `../srwz-patch-web/public/vocal.html` (from workspace root). It validates SHA-256 of all bytes outside VOCAL.BIN against a pinned experimental profile, locally decodes input, encodes with vendored Vorbis WASM quality 0, previews audio, and streams a new ISO. It can clear track 19 to restore native music. Ordinary SP/Z and different player builds are rejected. Never update the profile hash without revalidating the matching game build.

Evidence: `docs/issue-assets/sp-vocal-container-20261105/`; runtime commands and raw audio under `work/analysis/sp-vocal-container-20261105/`. ARMSX2 runner evidence is distinct from physical PS2 or manual emulator checks. Normal playback, native speech/effects, original fallback, stop/restart and EOF loop are exercised. The selected battle lasts about 84 seconds: the tail is tested separately by seeking to 180 seconds, not by claiming an uninterrupted 221-second battle. Telemetry word 27 is that internal test-only seek request (normally zero), words 28/29 seek result, 19 underruns, 30/31 fallback reason/count.

No main-Z profile, all-track support, general pause/fade coverage, or physical PS2 performance claim is made by this experiment.

## Current v2 extension (2026-11-06)

The live local editor now uses the v2 player under `work/analysis/sp-music-editor-20261106/payload`. All IDs 0..100 can be configured; IDs 19/20 were exercised at runtime. It hooks the shared native sequence-start RPC entry at `0x18c8a0` with an internal re-entry guard, instead of the synchronous-load epilogue. This covers both synchronous Battle Viewer and asynchronous Music Select starts. Unconfigured/invalid replacement entries restart the original score. Existing load/stop and pump hooks remain.

The header version is 2, profile `0x53500002`, still magic `SRWZVOC1` and the same 2048+256x64-byte layout. V1 remains readable. In v2, entry fields 7/8 give the sample-frame loop `[start,end)`, field 9 is Q16 software PCM gain (65536=unity, maximum 260904), and field 11 is 0=loop or 1=once; fields 12..15 remain zero. Loops preserve the intro from frame 0, then seek to start at each end. Once mode drains the queued PCM and restores the previous DMA-1 handler. Planned terminal silence is distinguished from buffer starvation. Encoded input limit stays 4 MiB per track, container 512 MiB shared.

`container.build_tracks()` creates the multi-track prefix. The local service validates ZIP package metadata, actual Vorbis rate/channels/frame count, loop points and gain, and supplies the prefix to `build_image`. Music titles are package metadata only; no native menu title edits or pilot/unit remapping are applied.

Evidence and precise limits: `docs/issue-assets/sp-music-editor-20261106/receipt.json`. The old v1 sections above document the previous single-track experiment; the current web UI and local server are described in the companion patch-web README.

## Z Original profile (2026-11-06)

`--game z` selects SLPS_258.87. `profiles.py` holds the verified SDK, BGM-state and hook mappings. The compiler translates only the known absolute addresses in the copied payload source, using a one-pass substitution so overlapping SDK addresses cannot be replaced twice. Main Z uses current BGM byte 0x5585d8 and native start RPC 0x18ac10. The payload still starts at 0x8c0000; the builder checks its actual end is below 0xdb0000, sets the kernel/user initialization base to 0xdb0000 and native break to 0xdc0000. Raw Original and known translated heap layouts are preimage-checked.

Stock Japanese Original and released Chinese v0.4.2 were exercised in ARMSX2 Music Select. Japanese-only navigation used a temporary RAM unlock to reach the same numbered song; Chinese v0.4.2 was already unlocked and used no RAM patch. This does not imply The Best, an arbitrary executable mod, or a complete gameplay playthrough has been validated.

`update_existing_image()` checks the exact linked player bytes and all hooks before updating an installed image. It changes only the fixed VOCAL.BIN extent, clears removed audio and compares every byte outside that extent to the source. Unknown player versions are rejected.

The shared container remains SRWZVOC1/v2 because original Z/SP music data and IDs were verified identical. Package target `srwz` denotes this shared library. The local service selects the executable profile from ISO members; frontend loop/gain/audio settings are shared.


## The Best profile (2026-11-06)

`--game best` targets SLPS_732.70 with independent guarded hooks and heap preimages. Stop/load/pump/native addresses are 0x189920/0x1899a0/0x189f10/0x18afb0, BGM byte 0x558dd8, native break word 0x3f4734. Shared SDK entry addresses remain the same as Original; native code functions shift by 0x3a0 while data moves by other deltas. Runtime test: complete 220.97-second song and full loop, sample-range loop matching FNV32 1096405404, 3-second once drain, unconfigured/restored native fallback, return stop, and one save-load/stage-entry smoke. No new Chinese Best or physical-console acceptance claim. See docs/issue-assets/best-vocal-20261106/receipt.json.

## v3 player (2026-11-11)

Installing on the v0.5.0 Chinese Original/Best (heap preimage 0x7a0000 from the event-caption payload, full program-header table) was first reported by Bilibili user 绯红之诗歌 (thanks). The battle sound-effect bug was reported by Bilibili user PicACGLite (thanks), with the affected Best ISO. Root cause fixed: v2 kept SPU2 core 1 AutoDMA (DMA 1) running while music played. The game uploads each attack's sound effects to SPU2 RAM through `sceSdVoiceTrans` channel 1, so those uploads failed and battles played stale samples (Best King Gainer battle: 91% of the sound-effect region wrong). The IRX now redirects the native modules' resolved libsd stubs (VoiceTrans / BlockTrans / SetTransIntrHandler) to wrappers that stop our AutoDMA before any native core-1 transfer; the EE restarts it once `sceSdVoiceTransStatus(1,0)` reports completion. Song changes no longer stop core 1 unconditionally. Disc reads use a second RPC server (`0x564f5243`) on their own IOP thread, so PCM requests never wait behind a CD read.

Playback starts before the song is fully loaded: the last 64 KiB (scanned by Tremor at open) and the first 64 KiB are read first, then the head is read only to keep 128 KiB ahead of the decoder (custom loop ranges and seeks read the rest at once; seeks wait for the whole song). Body CRC is still checked at the end. The PCM ring is 20 × 8 KiB blocks (was 16) and the file buffer 32 KiB (was 64), keeping the v2 IOP footprint: SP menus pause the audio update for ~0.6 s, which emptied the 16-block ring, and a 32-block ring crashed Original/Best battle loading (IOP memory).

The installer upgrades v1 and v2 images in place (exact payload hashes and per-version hook addresses in `profiles.LEGACY_PLAYERS`). ARMSX2 runner evidence (Best King Gainer battle, Best/Original enemy phase, SP Battle Viewer): SPU2 sound-effect region byte-identical to the release disc at matched moments; no underruns or fallbacks; replaced battle music starts ~0.2 s after the request; the battle itself starts ~0.4 s later than with an unreplaced song (disc contention). Best range-loop FNV 1096405404 matches the 2026-11-06 record; one-shot drains. Not a physical PS2 test.
