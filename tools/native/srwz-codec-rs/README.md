# SRWZ Rust codec

This crate is the repository-owned, clean-room high-performance production
encoder and decoder for the SRWZ byte stream documented in
`docs/SRWZ_COMPRESSION.md`.

It serializes the complete game-compatible block/token grammar. Its match
finder uses exact 2-, 4-, and 16-byte indexes, bounded short/medium chains, a
full long-match chain, exact compact-token byte gain, and the same deterministic
lazy-bias portfolio as the Python `maximum` strategy. By default it tries all
nine biases (`0..=8`) and keeps the smallest deterministic stream. Pass
`--lazy-bias N` to run only one bias when measuring the speed/size trade-off;
the accepted range is `0..=8`. Match quality parameters remain independent:
`--min-match-length` controls the shortest accepted match and
`--max-match-chain` bounds the candidate search. Production build transforms
use the Rust decoder and Rust round-trip. The strict Python decoder source is
retained only for format research and isolated comparison tests; no build,
extraction, verification, or acceptance workflow calls it.

Build the release binary through:

```bash
python3 tools/build_rust_compressor.py --force
```

The executable remains at the Cargo-owned, ignored path
`work/toolchain/srwz-compressor-rs/target/release/srwz-compress`; the build
does not copy the Mach-O/ELF to a second path.

Example of a single-pass experiment:

```bash
work/toolchain/srwz-compressor-rs/target/release/srwz-compress encode \
  --input decoded.bin \
  --output encoded.bin \
  --flags 29 \
  --header-unknown-1 0 \
  --min-match-length 3 \
  --max-match-chain 65535 \
  --lazy-bias 4
```

Always verify an experimental output with the Rust decoder and the original
byte budget before promoting it into an ISO.
