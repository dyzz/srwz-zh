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

Installing on the v0.5.0 Chinese Original/Best (heap preimage 0x7a0000 from the event-caption payload, full program-header table) was first reported by Bilibili user 绯红之诗 (thanks). The battle sound-effect bug was reported by Bilibili user PicACGLite (thanks), with the affected Best ISO. Root cause fixed: v2 kept SPU2 core 1 AutoDMA (DMA 1) running while music played. The game uploads each attack's sound effects to SPU2 RAM through `sceSdVoiceTrans` channel 1, so those uploads failed and battles played stale samples (Best King Gainer battle: 91% of the sound-effect region wrong). The IRX now redirects the native modules' resolved libsd stubs (VoiceTrans / BlockTrans / SetTransIntrHandler) to wrappers that stop our AutoDMA before any native core-1 transfer; the EE restarts it once `sceSdVoiceTransStatus(1,0)` reports completion. Song changes no longer stop core 1 unconditionally. Disc reads use a second RPC server (`0x564f5243`) on their own IOP thread, so PCM requests never wait behind a CD read.

Playback starts before the song is fully loaded: the last 64 KiB (scanned by Tremor at open) and the first 64 KiB are read first, then the head is read only to keep 128 KiB ahead of the decoder (custom loop ranges and seeks read the rest at once; seeks wait for the whole song). Body CRC is still checked at the end. The PCM ring is 20 × 8 KiB blocks (was 16) and the file buffer 32 KiB (was 64), keeping the v2 IOP footprint: SP menus pause the audio update for ~0.6 s, which emptied the 16-block ring, and a 32-block ring crashed Original/Best battle loading (IOP memory).

The installer upgrades v1 and v2 images in place (exact payload hashes and per-version hook addresses in `profiles.LEGACY_PLAYERS`). ARMSX2 runner evidence (Best King Gainer battle, Best/Original enemy phase, SP Battle Viewer): SPU2 sound-effect region byte-identical to the release disc at matched moments; no underruns or fallbacks; replaced battle music starts ~0.2 s after the request; the battle itself starts ~0.4 s later than with an unreplaced song (disc contention). Best range-loop FNV 1096405404 matches the 2026-11-06 record; one-shot drains. Not a physical PS2 test.

## v4 player (2026-11-11)

v3 still lost sound effects in the first battle after a replaced song began loading. The game's IOP loader reads each battle's sound-effect bank with `sceCdRead` in 32 KiB pieces and does not retry; a VOCAL.BIN read in flight (v3 reads while it plays) made those reads fail, the loader uploaded its stale buffer (the same piece up to six times), and the game then never keyed that bank, so the effects were silent rather than wrong. Reproduced on Best, Original and SP; holding the player's reads during the battle load restored a correct bank, which confirmed the cause.

The IRX now also redirects the native modules' `sceCdRead` stubs (cdvdman id 6, two modules) to a wrapper that waits for a file operation of ours to finish, and our file thread takes the drive only after it has been idle for 60 consecutive ~1 ms polls (`sceCdSync(1)`) with no native read being issued; it gives up after about 3 s. A read from interrupt context is passed straight through. The DMA-mode race in the `sceSdVoiceTrans` wrapper is closed as well: the channel stays marked busy until the native call returns. The IRX grew by 688 bytes; the ring and file buffer are unchanged.

The installer upgrades v1, v2 and v3 images in place. ARMSX2 runner evidence, same cold-boot routes as before (`route-main.txt` enemy phase for Best/Original, `route-sp.txt` Battle Viewer): voice key-ons at the sound-effect bank addresses match the release disc exactly (Best 14/14, Original 14/14, SP 29/29; v3 had 7, 7 and 16), no underruns or fallbacks, and the Best battle starts 17 frames later than on the release disc (v3: 38). Compare key-on lists, not raw SPU2 memory: the release and music discs can take different random battle branches. Not a physical PS2 test.

## v5 player (2026-11-13)

Player feedback on v4: in battle the music skipped briefly when the attacking side changed; map music was fine. Cause: at those moments (and at the start and end of a battle) the game uploads sound-effect banks on core 1 in bursts of 32 KiB pieces about 15 ms apart. v4 stopped the stream for every piece and restarted it from the EE one frame later, so one burst gave 5–8 stops, and each stop discarded up to two queued 8 KiB blocks. Measured with a timing log in the IRX (Best, complete battles): 8–9 stops per battle, 489–568 ms of silence in total.

The stream can now run on either core's block transfer. When the game is about to use the channel it is on, the IRX stops it, preserves the transfer-buffer remainder using `sceSdBlockTransStatus` (DMA position rounded down to 1024 bytes), and attempts to start it on the other core inside the same wrapper call; it returns to core 1 once that channel has been quiet for 150 ms. This DMA position is not a direct measurement of samples already output by SPU2. Core 0 also carries native speech uploads and occasional native block transfers. If a handoff cannot start, the preserved PCM waits for an EE retry. The core's input volume is saved and restored around our use. Refills take whole or partial ring blocks, and the worker refills a half only once so a stale signal cannot overwrite unplayed data. The ring is 19 blocks (was 20) to pay for an 8 KiB scratch buffer. Compared with v4, the reviewed/fixed IRX file grew by 2,656 bytes; the loaded segment span grew by 1,840 bytes, including 64 bytes of additional `.bss`.

Initial v5 measurements, before the review fixes below, reported 4–6 moves between cores per battle, 7–12 ms of interruption in total (longest 2.7 ms), no stops, and core-0 RMS within 0.5% of core 1. Those timing/RMS numbers were not remeasured in the independent review or fix validation. In SP the game itself ran a core 0 block transfer during the test and the stream moved out of its way. The installer upgrades v1–v4 images in place. ARMSX2 runner only; core 0 output and DMA handoff timing on a physical PS2 are not verified.

Review fixes (2026-11-13): a draining tail shorter than two blocks is padded with silence and can restart, including after both channels were busy. The EE retries inactive one-shots. During draining, RPC reply word 1 counts ring slots, preserved PCM and a nonzero DMA grace indicator; zero now means all three have drained. The IOP waits three half-transfer interrupts after the last ring data is taken (two halves plus one silent half for input-buffer latency), resetting that grace period after every successful start/move. This replaces the EE's old global-interrupt-count heuristic. STOP/new-song commands discard pending and partially consumed data explicitly. Failed AutoDMA starts restore the previous handler and keep the prepared buffer for retry without consuming it twice. Native transfer calls retain their busy guard through the real STOP/start return, and handler registration keeps its ownership check and real setter in one critical section.

Targeted host regressions compile the production PCM functions and EE drain helper with controlled libsd/interrupt stubs, under ASan/UBSan: `python3 -m unittest discover -s tests -p 'test_vocal*.py'` (11 PCM cases plus 8 container cases). Coverage includes all half/fresh combinations, partial ring consumption, tail relocation, busy-channel recovery, restart grace, handler/STOP interleavings on both cores, failed-start retry, stale signals and stop/reset. Reintroducing the old start/handler/STOP behavior or removing EE retry makes the corresponding regressions fail. These tests do not emulate hardware timing.

Fixed-build ARMSX2 evidence: `work/analysis/vocal-v5-fixes-20261113/` contains build/readback receipts, scripts, audio/key-on logs, counters, `runtime-battles.json`, `runtime-once.json`, and `mutation-check.json`. Best/Original were cold-booted through enemy-phase battle to frame 6080; key-ons from frame 3050 at addresses >= `0x88000` match the independent review's release recordings exactly (42/42 each, a longer window than the earlier 14-event report). SP records 29 key-ons at addresses >= `0x60000` after START over approximately 1500 frames. Its release reference has the same multiplicities at those addresses plus 50 events at six other addresses; this is a match on the candidate's address set, not a full 29/29 threshold-filtered release comparison. All three sampled zero underruns, fallbacks and deferred native handoffs; moves were 6/6/4. Separate container fixtures end each song after 960 PCM frames (one padded packet): all three return to stopped state with `song_finished=1`, `wanted=0`, zero underruns/fallbacks and three transfer interrupts. Tail migration and adversarial scheduling are host-test evidence, not injected hardware/runtime evidence. Relative to the pre-review v5, the fixes add 416 bytes of IOP `.text` and no `.bss` growth.
