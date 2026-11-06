# SP VOCAL.BIN player (experimental v1)

Isolated SLPS_259.20 Battle Viewer track 19 (Z Gundam). Not wired into release builds. The current SP release ISO is read-only; builds modify an APFS clone under `build/iso/test`.

## Playback

The complete Ogg Vorbis file is loaded through the game's IOP `cdrom0:\BGM\VOCAL.BIN;1` file interface. The ELF contains code and the PCM IRX only, not the song. EE normal-precision Tremor decodes 48 kHz stereo to PCM. The tiny IOP sink queues 512-byte channel blocks using existing libsd DMA 1; DMA 0 remains available for native speech. It restores the prior DMA-1 interrupt handler on stop. Compressed input is preloaded (4 MiB maximum per track); this is not continuous disc streaming.

The native BGM.BIN is byte-for-byte preserved. Track 19 stops its native score only when attempting replacement. Missing file, empty slot, invalid metadata/bounds/CRC, invalid Vorbis, mismatched frame count, or decode failure stops the replacement and restarts the already-loaded original score. Unconfigured tracks follow the native path. Only a single logical Vorbis stream and whole-track looping are supported.

Private EE range: `0x8c0000..0xdc0000`; both heap initialization and native break are adjusted. The gallery segment is preserved. Builds assert hook preimages, BGM hash, ELF capacity, payload bounds and unchanged bytes outside the explicit patch spans. ISO9660, VMAP and UDF all name the new file. Original source extents remain in place except relocated ELF and extended metadata.

## Container ABI

`container.py` and browser `vocal-container.mjs` serialize the same bytes (cross-language test).

- Capacity: 512 MiB, shared across tracks; current runtime enables track 19 only.
- Header: 2048 bytes, magic `SRWZVOC1`, version 1, SP profile `0x53500001`.
- Index: 256 slots × 64 bytes, at relative offset 2048; data starts at 18432.
- `<14I` at header byte 8: version, header size, index offset, entry size, slot count, data offset, used bytes, capacity, profile, index CRC32, header CRC32, flags 0, reserved 0, reserved 0. Header CRC is over all 2048 bytes with its own word (byte 48) zeroed.
- Entry `<16I`: track ID, active flag, relative byte offset, encoded byte length, sample rate, channels, PCM frames, loop start, loop end, gain Q15, body CRC32, five reserved zeros.
- Track data is aligned to 2048 bytes. v1 accepts 48000 Hz, stereo, loop `[0, frames)`, gain `0..0x7fff` (default `0x4800`), encoded size at most 4 MiB. Empty entries contain their slot ID and all other fields zero.
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
