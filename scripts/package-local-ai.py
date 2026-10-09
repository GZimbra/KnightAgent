"""Split and restore the local Ollama model store for GitHub release assets."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re


MANIFESTS = (
    "manifests/registry.ollama.ai/library/qwen2.5/7b",
    "manifests/registry.ollama.ai/library/knightagent-automation/latest",
)
BUFFER = 8 * 1024 * 1024
PART_LIMIT = 1800 * 1024 * 1024


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(BUFFER):
            digest.update(block)
    return digest.hexdigest()


def model_files(models):
    paths = set(MANIFESTS)
    for name in MANIFESTS:
        manifest = json.loads((models / name).read_text(encoding="utf-8"))
        for layer in (manifest["config"], *manifest["layers"]):
            match = re.fullmatch(r"sha256:([0-9a-f]{64})", layer["digest"])
            if not match:
                raise ValueError(f"Invalid digest in {name}")
            blob = f"blobs/sha256-{match.group(1)}"
            if (models / blob).stat().st_size != layer["size"] or digest_file(models / blob) != match.group(1):
                raise ValueError(f"Model blob failed verification: {blob}")
            paths.add(blob)
    return sorted(paths)


def pack(root, output, part_limit=PART_LIMIT):
    if part_limit < BUFFER:
        raise ValueError("Part limit must be at least 8 MiB")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty")
    files = [f"runtime/models/{name}" for name in model_files(root / "runtime/models")]
    files.append("docs/licenses/OLLAMA-LICENSE.txt")
    runtime = root / "runtime/ollama"
    if not (runtime / "ollama.exe").is_file():
        raise ValueError("Private Ollama runtime missing")
    for path in runtime.rglob("*"):
        if path.is_symlink():
            raise ValueError("Runtime links are not allowed")
        if path.is_file():
            files.append(path.relative_to(root).as_posix())
    files.sort()
    entries, parts = [], []
    current = None
    written = 0
    part_hash = None

    def open_part():
        nonlocal current, written, part_hash
        name = f"knightagent-local-ai.part{len(parts) + 1:03d}"
        current = (output / name).open("wb")
        written = 0
        part_hash = hashlib.sha256()
        parts.append({"name": name, "size": 0, "sha256": ""})

    def close_part():
        nonlocal current
        if current is not None:
            current.close()
            parts[-1].update(size=written, sha256=part_hash.hexdigest())
            current = None

    try:
        for name in files:
            source_path = root / name
            file_hash = hashlib.sha256()
            chunks = []
            with source_path.open("rb") as source:
                while block := source.read(BUFFER):
                    file_hash.update(block)
                    position = 0
                    while position < len(block):
                        if current is None:
                            open_part()
                        take = min(len(block) - position, part_limit - written)
                        piece = block[position:position + take]
                        chunks.append({"part": len(parts) - 1, "offset": written, "size": take})
                        current.write(piece)
                        part_hash.update(piece)
                        written += take
                        position += take
                        if written == part_limit:
                            close_part()
            entries.append({"path": name, "size": source_path.stat().st_size,
                            "sha256": file_hash.hexdigest(), "chunks": chunks})
        close_part()
        document = {"format": 1, "models": list(MANIFESTS), "parts": parts, "files": entries}
        (output / "knightagent-local-ai.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return document
    finally:
        close_part()


def restore(package, root):
    document = json.loads((package / "knightagent-local-ai.json").read_text(encoding="utf-8"))
    if document.get("format") != 1 or document.get("models") != list(MANIFESTS):
        raise ValueError("Unsupported model package")
    parts = document["parts"]
    for part in parts:
        name = part["name"]
        if not re.fullmatch(r"knightagent-local-ai\.part\d{3}", name):
            raise ValueError("Invalid part name")
        path = package / name
        if path.stat().st_size != part["size"] or digest_file(path) != part["sha256"]:
            raise ValueError(f"Part failed verification: {name}")
    allowed = {f"runtime/models/{name}" for name in MANIFESTS}
    allowed.add("docs/licenses/OLLAMA-LICENSE.txt")
    for entry in document["files"]:
        name = entry["path"]
        if (name not in allowed
                and not re.fullmatch(r"runtime/models/blobs/sha256-[0-9a-f]{64}", name)
                and not (name.startswith("runtime/ollama/") and all(
                    segment not in ("", ".", "..") for segment in name.split("/")))):
            raise ValueError("Invalid file path")
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".partial")
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("wb") as destination:
                for chunk in entry["chunks"]:
                    part = parts[chunk["part"]]
                    with (package / part["name"]).open("rb") as source:
                        source.seek(chunk["offset"])
                        remaining = chunk["size"]
                        while remaining:
                            block = source.read(min(BUFFER, remaining))
                            if not block:
                                raise ValueError("Truncated part")
                            destination.write(block)
                            digest.update(block)
                            size += len(block)
                            remaining -= len(block)
            if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                raise ValueError(f"File failed verification: {name}")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    model_files(root / "runtime/models")
    if not (root / "runtime/ollama/ollama.exe").is_file():
        raise ValueError("Restored Ollama runtime missing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pack", "restore"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "pack":
        document = pack(args.root, args.package)
        print(f"Created {len(document['parts'])} verified parts in {args.package}")
    else:
        restore(args.package, args.root)
        print(f"Restored and verified local AI in {args.root}")


if __name__ == "__main__":
    main()
