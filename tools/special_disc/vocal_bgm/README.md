# VOCAL.BIN player (SP / Z / The Best)

Replaces the game's BGM with Ogg Vorbis tracks of your own, by adding a small
decoder to the game executable and a new `BGM/VOCAL.BIN` file to the disc.
`BGM.BIN` itself is never modified; any track left unconfigured, or that fails
validation, plays the original score.

Three executables are supported, each with its own address profile in
`profiles.py`: Special Disc (`SLPS_259.20`), Z Original (`SLPS_258.87`) and
The Best (`SLPS_732.70`). Music Select and Battle Viewer share BGM IDs 0–100.

This directory is self-contained: the player source, the container format and
the installer live here, and the only external inputs are the two pinned
upstreams in `upstream.lock.json`. The web tool at `/music/` builds discs with
exactly this code, running `container.py` under Pyodide.

## Build

Neither upstream is vendored here:

| Dependency | Pin | Licence |
| --- | --- | --- |
| [ps2dev](https://github.com/ps2dev/ps2dev/releases/tag/v2.0.0) toolchain (EE/IOP GCC 15.2.0 + PS2SDK) | `v2.0.0`, asset `ps2dev-macos-latest.tar.gz` | per upstream |
| [citronalco/ps2-libtremor](https://github.com/citronalco/ps2-libtremor) (Xiph Tremor, fixed-point Vorbis) | commit `ae62505aee8f4fc15cce97332133229ed8da0d5a` | BSD-3-Clause, `licenses/` |

Also needed: Python 3, `ffprobe`, and a 48 kHz stereo Vorbis file of at most
4 MiB. PS2SDK libogg ships inside the ps2dev toolchain.

Extract the ps2dev release and point `--toolchain` at its root (the directory
holding `ee/`, `iop/` and `ps2sdk/`). Tremor is fetched for you — into
`work/toolchain/ps2-libtremor-<short>/`, which git ignores:

```sh
# optional: build_candidate.py runs this itself when --tremor-source is omitted
python3 tools/special_disc/vocal_bgm/bootstrap_tremor.py
```

Then, from `srwz-zh`:

```sh
python3 tools/special_disc/vocal_bgm/build_candidate.py \
  --game sp \
  --ogg /path/to/song.ogg \
  --toolchain /path/to/ps2dev \
  --workdir work/analysis/sp-vocal-rebuild \
  --output-iso build/iso/test/sp-vocal-rebuild.iso
```

`--game` selects `sp`, `z` or `best`. `--payload-only` stops after
`payload.bin` and needs no source ISO. `--tremor-source` overrides the managed
checkout. Use `--replace` only for a test image you own.

To encode a song at the default nominal 64 kbit/s VBR (quality 0), with an
ffmpeg built with libvorbis:

```sh
ffmpeg -i input.mp3 -ar 48000 -ac 2 -c:a libvorbis -q:a 0 song.ogg
```

Resampling does not improve the source, and the real average bitrate depends on
the song.

The build is reproducible: with the pins above the three v5 payloads rebuild
byte-identically (`payload.bin` sha256 `8f1b1a83…` best, `9253029f…` z,
`587d4c51…` sp; verified 2026-11-13). GCC 15 emits legacy `int*`/`long*`
warnings from Tremor on 32-bit EE types; the compile uses `-fno-strict-aliasing`
and they are expected.

Host regressions compile the production PCM functions and the EE drain helper
against controlled libsd/interrupt stubs under ASan/UBSan:

```sh
python3 -m unittest discover -s tests -p 'test_vocal*.py'
```

That is 11 PCM cases and 8 container cases. They cover half/fresh refill
combinations, partial ring consumption, tail relocation, busy-channel recovery,
restart grace, handler/STOP interleavings on both cores, failed-start retry,
stale signals and stop/reset — but they do not emulate hardware timing.

## How it works

**Loading.** Tracks are read from `cdrom0:\BGM\VOCAL.BIN;1` over a dedicated
non-blocking SIF RPC client with its own IOP thread, so a PCM request never
queues behind a CD read. Playback begins before the whole song has arrived: the
last 64 KiB (Tremor scans it when opening) and the first 64 KiB are read first,
then the head is kept 128 KiB ahead of the decoder. Custom loop ranges and
seeks read the remainder at once. The body CRC is still checked at the end.

**Decoding and output.** Tremor (EE, normal precision) decodes at most one
packet per update-hook call. The IOP sink feeds SPU2 through a block transfer
in a ring of 19 × 8 KiB blocks, with a 32 KiB file buffer and an 8 KiB scratch
buffer. The stream can run on either SPU2 core and moves out of the way of the
game's own transfers (see *Sharing SPU2* below).

**Fallback.** A missing entry, or invalid metadata, bounds, CRC, Vorbis data or
frame count, restarts the already-loaded native score. The fallback path guards
the native start hook against re-entry.

**Memory.** The payload occupies the private EE range `0x8c0000..0xdc0000`;
heap initialization and the native break are moved accordingly, and the gallery
segment is preserved. The build asserts hook preimages, the BGM hash, ELF
capacity, payload bounds and that no byte outside the explicit patch spans
changed. ISO9660, VMAP and UDF all name the new file.

**Upgrading an existing disc.** `update_existing_image()` recognises installed
v1–v4 players on all three games by exact payload hash and hook addresses
(`profiles.LEGACY_PLAYERS`), rewrites only the fixed VOCAL.BIN extent and the
ELF, and compares every other byte to the source. Songs and gain settings
survive. An unknown player build or a changed hook is rejected, and a base ISO
is required instead. Cold-boot the result: an old savestate still holds the old
code.

## Sharing SPU2 with the game

Most of the player's complexity is co-existing with the game's own audio. The
game uploads sound-effect banks to SPU2 RAM and reads them from the disc while
music is playing, and early versions broke both. Three rules now apply, each
added in response to a reported bug:

- **Never hold a channel the game wants.** The IRX redirects the native
  modules' resolved libsd stubs (`sceSdVoiceTrans`, `sceSdBlockTrans`,
  `sceSdSetTransIntrHandler`). Before any native core-1 transfer, the player
  gets out of the way; the channel stays marked busy until the native call
  returns.
- **Never read the disc while the game does.** The game's loader reads each
  battle's sound-effect bank with `sceCdRead` in 32 KiB pieces and does not
  retry, so a read of ours in flight made those reads fail silently. The IRX
  redirects the native `sceCdRead` stubs (cdvdman id 6, two modules); our file
  thread takes the drive only after 60 consecutive ~1 ms polls
  (`sceCdSync(1)`) with no native read, and gives up after about 3 s. Reads
  from interrupt context pass straight through.
- **Move, don't stop.** When the game needs the core the stream is on, the IRX
  preserves the transfer-buffer remainder via `sceSdBlockTransStatus` (DMA
  position rounded down to 1024 bytes) and restarts the stream on the other
  core within the same wrapper call, returning to core 1 once that channel has
  been quiet for 150 ms. That DMA position is not a direct measurement of what
  SPU2 has already played. Core 0 also carries native speech, so a handoff can
  fail; the preserved PCM then waits for an EE retry. The core's input volume
  is saved and restored around our use.

A draining tail shorter than two blocks is padded with silence and can restart.
STOP and new-song commands explicitly discard pending and partially consumed
data. A failed start restores the previous handler and keeps the prepared
buffer for retry without consuming it twice.

## Container ABI

`container.py` is the single serializer, used by the CLI and, through Pyodide,
by the web tool.

- Capacity: 512 MiB shared across tracks; runtime IDs 0–100, 256 directory slots.
- Header: 2048 bytes, magic `SRWZVOC1`, version 1 / 2, profile `0x53500001` / `0x53500002`.
- Index: 256 slots × 64 bytes at relative offset 2048; data starts at 18432.
- `<14I` at header byte 8: version, header size, index offset, entry size, slot count, data offset, used bytes, capacity, profile, index CRC32, header CRC32, flags 0, reserved 0, reserved 0. The header CRC covers all 2048 bytes with its own word (byte 48) zeroed.
- Entry `<16I`: track ID, active flag, relative byte offset, encoded byte length, sample rate, channels, PCM frames, loop start, loop end, gain, body CRC32, one-shot flag (v2), four reserved zeros.
- Track data is aligned to 2048 bytes. Empty entries hold their slot ID and zeros.
- v1: 48000 Hz, stereo, loop `[0, frames)`, gain `0..0x7fff` (default `0x4800`, native-volume semantics), at most 4 MiB encoded.
- v2: gain is Q16 (65536 = unity, maximum 260904); fields 7/8 are the sample-frame loop `[start, end)` with `0 <= start < end <= frames`; field 11 is 0 = loop or 1 = once. Loops play the intro from frame 0, then seek to `start` at each end. Once mode drains the queued PCM and stops; planned terminal silence is distinguished from buffer starvation. v1 containers remain readable.
- CRC32 is the standard reflected form, polynomial `0xedb88320`, initial/final XOR `0xffffffff`.

## Verification status

All runtime evidence comes from the headless ARMSX2 runner. **No version has
been tested on a physical PS2**, and core-0 output and DMA-handoff timing in
particular are unverified there.

Current (v5, 2026-11-13), from `work/analysis/vocal-v5-fixes-20261113/`
(receipts, scripts, audio and key-on logs, counters, `runtime-battles.json`,
`runtime-once.json`, `mutation-check.json`):

- Best and Original, cold-booted through an enemy-phase battle to frame 6080: voice key-ons from frame 3050 at addresses ≥ `0x88000` match the release disc exactly, 42/42 each.
- SP records 29 key-ons at addresses ≥ `0x60000` after START over ~1500 frames. The release reference has the same multiplicities at those addresses plus 50 events at six others, so this is a match on the candidate's address set, not a full threshold-filtered comparison.
- All three sampled zero underruns, zero fallbacks and zero deferred native handoffs; core moves were 6/6/4.
- Container fixtures ending a song after 960 PCM frames return to stopped state on all three with `song_finished=1`, `wanted=0`, zero underruns/fallbacks and three transfer interrupts.
- Tail migration and adversarial scheduling are host-test evidence only.

Compare key-on lists rather than raw SPU2 memory: a music disc and the release
disc can take different random battle branches.

Earlier per-version measurements (v3 start latency, pre-fix v5 handoff timing
and RMS) were not re-measured against the current build and are kept only in
the history below.

## Version history

- **v1** (2026-11-05) — single-track SP experiment. Whole-song preload, hooked the synchronous-load epilogue.
- **v2** (2026-11-06) — all IDs 0–100, container v2 (range loop, one-shot, Q16 gain). Hooks the shared native sequence-start RPC with a re-entry guard, covering both Battle Viewer and Music Select. Z Original and The Best profiles added; the container is shared because Z and SP music data and IDs were verified identical.
- **v3** (2026-11-11) — installs on v0.5.0 Chinese Original/Best; streams instead of preloading. Fixed battle sound effects playing stale samples: v2 held SPU2 core 1 AutoDMA while music played, so the game's uploads failed. Reported by Bilibili user PicACGLite; v0.5.0 installation reported by 绯红之诗.
- **v4** (2026-11-11) — fixed sound effects going silent in the first battle after a song began loading: our disc reads made the game's non-retrying `sceCdRead` fail, so a bank was never keyed. Added disc-read arbitration and closed a DMA-mode race in the transfer wrapper.
- **v5** (2026-11-13) — fixed music skipping when the attacking side changed. v4 stopped the stream for every 32 KiB piece of a sound-effect burst (8–9 stops and 489–568 ms of silence per battle); v5 moves the stream to the other core instead. Review fixes the same day replaced an EE interrupt-count heuristic with an IOP grace period of three half-transfer interrupts, and hardened restart, STOP and handler-registration paths.
