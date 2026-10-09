import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import hashlib


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "package-local-ai.py"
SPEC = importlib.util.spec_from_file_location("package_local_ai", MODULE_PATH)
package_ai = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_ai)


class PackageLocalAiTests(unittest.TestCase):
    def test_split_restore_and_reject_corrupt_part(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "runtime" / "models"
            runtime = root / "runtime" / "ollama"
            runtime.mkdir(parents=True)
            (runtime / "ollama.exe").write_bytes(b"runtime-test")
            license_file = root / "docs" / "licenses" / "OLLAMA-LICENSE.txt"
            license_file.parent.mkdir(parents=True)
            license_file.write_text("MIT License", encoding="utf-8")
            blob = b"model" * (2 * 1024 * 1024)
            digest = hashlib.sha256(blob).hexdigest()
            blob_path = models / "blobs" / f"sha256-{digest}"
            blob_path.parent.mkdir(parents=True)
            blob_path.write_bytes(blob)
            manifest = {"config": {"digest": f"sha256:{digest}", "size": len(blob)}, "layers": []}
            for name in package_ai.MANIFESTS:
                path = models / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(manifest), encoding="utf-8")
            package = root / "package"
            document = package_ai.pack(root, package, part_limit=package_ai.BUFFER)
            self.assertEqual(len(document["parts"]), 2)
            restored = root / "restored"
            package_ai.restore(package, restored)
            self.assertEqual((restored / "runtime" / "models" / "blobs" / f"sha256-{digest}").read_bytes(), blob)
            first = package / document["parts"][0]["name"]
            with first.open("r+b") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "Part failed verification"):
                package_ai.restore(package, root / "invalid")


if __name__ == "__main__":
    unittest.main()
