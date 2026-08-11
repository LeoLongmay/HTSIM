import os
import pathlib
import shutil
import subprocess
import unittest


SMOKE = pathlib.Path(__file__).resolve().parents[2]
DATACENTER_CMAKE = SMOKE.parents[2] / "CMakeLists.txt"
RUNNER = SMOKE / "strict_reproduction" / "repro.sh"


class StrictReproductionIsolationTests(unittest.TestCase):
    def test_runner_disables_only_the_source_symlink_hook(self):
        cmake = DATACENTER_CMAKE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("option(HTSIM_CREATE_SOURCE_SYMLINKS", cmake)
        self.assertIn("if (HTSIM_CREATE_SOURCE_SYMLINKS)", cmake)
        self.assertIn("-DHTSIM_CREATE_SOURCE_SYMLINKS=OFF", runner)

    def test_runner_leaves_source_idmap_unchanged(self):
        source_idmap = SMOKE.parents[2] / "idmap.txt"
        existed = source_idmap.exists()
        before = source_idmap.read_bytes() if existed else None
        sentinel = b"strict-reproduction-source-idmap-sentinel\n"
        output = SMOKE / "runs" / f"strict_containment_{os.getpid()}"
        self.assertFalse(output.exists())
        try:
            source_idmap.write_bytes(sentinel)
            result = subprocess.run(
                ["bash", str(RUNNER), "--out", str(output)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(sentinel, source_idmap.read_bytes())
        finally:
            shutil.rmtree(output, ignore_errors=True)
            if existed:
                source_idmap.write_bytes(before)
            else:
                source_idmap.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
