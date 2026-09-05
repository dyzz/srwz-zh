import io
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz import codec, codec_worker


@unittest.skipUnless(codec._rust_compressor_path().is_file(), "build the Rust codec first")
class CodecWorkerTests(unittest.TestCase):
    def tearDown(self):
        codec_worker.close_workers()

    def test_payload_matches_one_shot_cli_with_prefix_and_parse_profiles(self):
        rng = random.Random(932)
        data = bytes(rng.randrange(256) for _ in range(4096))
        data += data[:3000] * 3 + b"abcabc" * 1000
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input").write_bytes(data)
            for prefix, bias, chain in ((0, 0, 64), (1024, 4, 128), (4096, None, 256)):
                with self.subTest(prefix=prefix, bias=bias):
                    arguments = [str(codec._rust_compressor_path()), "payload",
                                 "--input", str(root / "input"), "--output", str(root / "output"),
                                 "--window-size", "16384", "--prefix-size", str(prefix),
                                 "--min-match-length", "2", "--max-match-chain", str(chain)]
                    if bias is not None:
                        arguments += ["--lazy-bias", str(bias)]
                    subprocess.run(arguments, check=True, capture_output=True)
                    result = codec._rust_payload(data, window_size=16384,
                                                 prefix_size=prefix, min_match_length=2,
                                                 search_chain=chain, lazy_bias=bias)
                    self.assertEqual(result, (root / "output").read_bytes())

    def test_decode_metadata_and_padding_match_python_oracle(self):
        for source in (b"", b"x", bytes(range(256)), b"abcdefgh" * 5000):
            with self.subTest(size=len(source)):
                encoded = codec.encode(source, strategy="rust-fit") + bytes(57)
                self.assertEqual(codec.decode_production(encoded), codec.decode(encoded))

    def test_repeated_decode_reuses_process_and_recovers_after_codec_error(self):
        encoded = codec.encode(b"safe stream" * 80, strategy="rust-fit")
        expected = codec.decode_production(encoded)
        pid = codec_worker._local.worker.process.pid
        for malformed in (b"", b"\0", b"broken", encoded[:-1]):
            with self.assertRaises(codec.SrwzCodecError):
                codec.decode_production(malformed)
            self.assertEqual(codec.decode_production(encoded), expected)
            self.assertEqual(codec_worker._local.worker.process.pid, pid)

    def test_workers_do_not_mix_concurrent_frames(self):
        def round_trip(index):
            source = bytes([index]) * (1000 + index) + bytes(range(256))
            encoded = codec.encode(source, strategy="rust-fit")
            self.assertEqual(codec.decode_production(encoded).output, source)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(round_trip, range(64)))

    def test_dead_worker_is_replaced_before_next_request(self):
        encoded = codec.encode(b"restart" * 100, strategy="rust-fit")
        old = codec_worker._local.worker.process
        old.kill()
        old.wait()
        self.assertEqual(codec.decode_production(encoded).output, b"restart" * 100)
        self.assertNotEqual(codec_worker._local.worker.process.pid, old.pid)

    def test_binary_identity_change_restarts_the_worker(self):
        encoded = codec.encode(b"binary replacement", strategy="rust-fit")
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "codec"
            shutil.copy2(codec._rust_compressor_path(), binary)
            expected = codec_worker.request(binary, 0, encoded)
            old_pid = codec_worker._local.worker.process.pid
            binary.touch()
            self.assertEqual(codec_worker.request(binary, 0, encoded), expected)
            self.assertNotEqual(codec_worker._local.worker.process.pid, old_pid)

    def test_invalid_encode_request_keeps_worker_synchronized(self):
        with self.assertRaises(codec_worker.CodecWorkerError):
            codec._rust_payload(b"input", window_size=0, min_match_length=2, search_chain=64)
        self.assertEqual(codec.decode_production(codec.encode(b"valid")).output, b"valid")

    def test_truncated_transport_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            codec_worker._read_exact(io.BytesIO(b"short"), 10)


if __name__ == "__main__":
    unittest.main()
