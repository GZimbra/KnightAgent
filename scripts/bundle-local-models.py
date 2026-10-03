"""Copy the two installed models into the application, verifying SHA-256 offline."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def main():
    root = Path(__file__).resolve().parent.parent
    source = Path.home() / ".ollama" / "models"
    target = root / "runtime" / "models"
    (target / "blobs").mkdir(parents=True, exist_ok=True)
    manifests = [Path("manifests/registry.ollama.ai/library/knightagent-automation/latest"),
                 Path("manifests/registry.ollama.ai/library/qwen2.5/7b")]
    verified = set()
    total = 0
    for relative in manifests:
        raw = (source / relative).read_bytes()
        manifest = json.loads(raw)
        for layer in [manifest["config"], *manifest["layers"]]:
            digest = layer["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Invalid local model digest")
            if digest in verified:
                continue
            filename = digest.replace(":", "-")
            hasher = hashlib.sha256()
            size = 0
            temporary = None
            try:
                with (source / "blobs" / filename).open("rb") as incoming, tempfile.NamedTemporaryFile(
                        dir=target / "blobs", prefix=".copy-", delete=False) as outgoing:
                    temporary = Path(outgoing.name)
                    while chunk := incoming.read(8 * 1024 * 1024):
                        hasher.update(chunk)
                        size += len(chunk)
                        outgoing.write(chunk)
                if size != layer["size"] or hasher.hexdigest() != digest[7:]:
                    raise ValueError("Local model blob failed size/SHA-256 validation")
                os.replace(temporary, target / "blobs" / filename)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            total += size
            verified.add(digest)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    report = {"models": [str(path) for path in manifests], "verified_blobs": len(verified),
              "verified_bytes": total, "target": str(target), "downloads": 0}
    (root / "build" / "bundled-models.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
