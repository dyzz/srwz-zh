"""A step is skipped only while everything it read is unchanged; what it wrote is put back exactly."""
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz import file_identity
from srwz.step_memo import Step, StepError

STEP = textwrap.dedent('''
    import json, os, sys
    from pathlib import Path
    project, frontend = Path(sys.argv[1]), Path(sys.argv[2])
    text = (project / "corpus/used.txt").read_text() + (frontend / "member.bin").read_text()
    names = sorted(os.listdir(frontend / "pictures"))
    (project / "work").mkdir(exist_ok=True)
    (project / "work/out.txt").write_text(text + ",".join(names))
    (project / "config/lock.json").write_text(json.dumps({"n": len(text)}))
    (project / "corpus/obsolete.txt").unlink(missing_ok=True)
    tool = project / "tools/constant.py"                     # a step may rewrite a constant in a tool source
    tool.write_text(tool.read_text().replace("OLD", "sha-of-" + text))
    counter = Path(sys.argv[3]); counter.write_text(str(int(counter.read_text() or 0) + 1))
''')


class StepMemoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        env = mock.patch.dict(os.environ, {file_identity.ENV_STORE: str(self.root / "ids.json")})
        env.start(); self.addCleanup(env.stop)
        file_identity.forget_all(); self.addCleanup(file_identity.forget_all)
        # Python lists the directory of the script it runs (imports): the script has one of its own
        (self.root / "tool").mkdir()
        (self.root / "tool/step.py").write_text(STEP)
        self.counter = self.root / "runs"; self.counter.write_text("0")
        self.frontend = self.root / "frontend-a"
        (self.frontend / "pictures").mkdir(parents=True)
        (self.frontend / "member.bin").write_text("member")
        (self.frontend / "pictures/one.png").write_text("1")
        (self.frontend / "unread.bin").write_text("x")

    def project(self, name, used="used", unused="unused"):
        project = self.root / name
        for path, text in (("corpus/used.txt", used), ("corpus/unused.txt", unused),
                           ("corpus/obsolete.txt", "old"), ("config/lock.json", "{}"),
                           ("tools/constant.py", "BASE = 'OLD'\n")):
            (project / path).parent.mkdir(parents=True, exist_ok=True)
            (project / path).write_text(text)
        return project

    def run_step(self, project, frontend=None, verify=False, scope="v1"):
        frontend = frontend or self.frontend
        step = Step("toy", self.root / "store", project, self.root, scope=scope, roots={"frontend": frontend},
                    ignore=("runs",), untracked=("caller.log",),      # the run counter and log are the test's own
                    log=lambda line: None)
        return step.run([sys.executable, str(self.root / "tool/step.py"), str(project), str(frontend), str(self.counter)],
                        cwd=project, verify=verify)

    def runs(self):
        return int(self.counter.read_text())

    def test_unchanged_reads_put_the_outputs_back_without_running(self):
        first = self.project("p1")
        self.assertFalse(self.run_step(first))
        (first / "caller.log").write_text("first build")
        second = self.project("p2", unused="edited elsewhere")
        (second / "caller.log").write_text("second build")
        self.assertTrue(self.run_step(second))
        self.assertEqual((second / "caller.log").read_text(), "second build")   # never replaced by a record
        self.assertEqual(self.runs(), 1)
        for path in ("work/out.txt", "config/lock.json", "tools/constant.py"):
            self.assertEqual((second / path).read_bytes(), (first / path).read_bytes())
        self.assertFalse((second / "corpus/obsolete.txt").exists())          # removals are replayed too
        self.assertEqual((second / "corpus/unused.txt").read_text(), "edited elsewhere")

    def test_a_changed_read_runs_the_step_again(self):
        self.run_step(self.project("p1"))
        self.assertFalse(self.run_step(self.project("p2", used="other text")))
        self.assertEqual(self.runs(), 2)
        self.assertTrue(self.run_step(self.project("p3", used="other text")))   # both records are kept
        self.assertTrue(self.run_step(self.project("p4")))
        self.assertEqual(self.runs(), 2)

    def test_reads_in_a_named_root_follow_the_root_to_its_new_place(self):
        self.run_step(self.project("p1"))
        moved = self.root / "frontend-b"
        os.rename(self.frontend, moved)
        (moved / "unread.bin").write_text("changed, but never read")
        self.assertTrue(self.run_step(self.project("p2"), frontend=moved))
        (moved / "member.bin").write_text("another member")
        self.assertFalse(self.run_step(self.project("p3"), frontend=moved))
        (moved / "pictures/two.png").write_text("2")                         # a listed directory gained a file
        self.assertFalse(self.run_step(self.project("p4"), frontend=moved))
        self.assertEqual(self.runs(), 3)

    def test_scope_and_file_names_bound_a_record(self):
        self.run_step(self.project("p1"))
        self.assertFalse(self.run_step(self.project("p2"), scope="v2"))
        extra = self.project("p3"); (extra / "corpus/new.txt").write_text("a file the step may look for")
        self.assertFalse(self.run_step(extra))
        self.assertEqual(self.runs(), 3)

    def test_verify_runs_the_step_and_rejects_a_record_that_does_not_reproduce_it(self):
        self.run_step(self.project("p1"))
        self.assertFalse(self.run_step(self.project("p2"), verify=True))
        self.assertEqual(self.runs(), 2)
        record = next((self.root / "store/toy").glob("*/*/files/work/out.txt"))
        record.write_text("tampered")
        with self.assertRaisesRegex(StepError, "does not reproduce"):
            self.run_step(self.project("p3"), verify=True)

    def test_a_dictionary_asked_entry_by_entry_counts_by_its_answers(self):
        tools = str(Path(__file__).resolve().parents[1] / "tools")
        (self.root / "tool/ask.py").write_text(textwrap.dedent(f'''
            import sys
            sys.path.insert(0, {tools!r})
            from pathlib import Path
            from srwz.build_language import expected_literal
            project = Path(sys.argv[1])
            answer = expected_literal("简体", project) + expected_literal("没有这句", project)
            (project / "work").mkdir(exist_ok=True)
            (project / "work/answer.txt").write_text(answer)
            counter = Path(sys.argv[2]); counter.write_text(str(int(counter.read_text() or 0) + 1))
        '''))

        def build(name, extra):
            project = self.project(name)
            (project / "config/zh-hant").mkdir(parents=True)
            literals = {"简体": "簡體", "没有这句": "沒有這句", **extra}
            (project / "config/zh-hant/readback-literals.json").write_text(json.dumps(
                {"literals": literals}, ensure_ascii=False))
            step = Step("ask", self.root / "store", project, self.root, scope="v1", ignore=("runs",),
                        log=lambda line: None)
            reused = step.run([sys.executable, str(self.root / "tool/ask.py"), str(project), str(self.counter)],
                              cwd=project)
            return reused, (project / "work/answer.txt").read_text()

        self.assertEqual(build("p1", {}), (False, "簡體沒有這句"))
        # the dictionary grew by a line nobody asked for: its bytes changed, its answers did not
        self.assertEqual(build("p2", {"别的台词": "別的臺詞"}), (True, "簡體沒有這句"))
        # an answer that was asked for changed
        self.assertEqual(build("p3", {"没有这句": "現在有了"}), (False, "簡體現在有了"))
        self.assertEqual(self.runs(), 2)


if __name__ == "__main__":
    unittest.main()
