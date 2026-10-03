import difflib
import itertools
import ntpath
import os
from pathlib import Path
import re
import stat


class FileSafetyError(ValueError):
    pass


def bounded(text, limit):
    marker = "\n[SAIDA TRUNCADA: refine a busca ou leia outro trecho.]"
    return text if len(text) <= limit else text[:max(0, limit - len(marker))] + marker


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise FileSafetyError("Workspace deve ser um diretorio existente.")

    def path(self, value):
        # Somente caminhos relativos portaveis. Evita drives, UNC, ADS e device paths.
        if not isinstance(value, str) or not value or '\x00' in value:
            raise FileSafetyError("Caminho vazio ou invalido.")
        drive, _ = ntpath.splitdrive(value)
        if drive or value.startswith(("/", "\\")):
            raise FileSafetyError("Use caminho relativo ao workspace; unidades e UNC sao bloqueados.")
        parts = value.replace("\\", "/").split("/")
        for part in parts:
            if part == ".":
                continue
            if not part or part == ".." or part.endswith((" ", ".")) or re.search(r'[<>:"|?*\x00-\x1f]', part):
                raise FileSafetyError("Componente de caminho inseguro.")
            stem = part.split(".")[0].upper()
            if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem):
                raise FileSafetyError("Nome reservado do Windows.")
        candidate = self.root.joinpath(*parts)
        # Politica conservadora: rejeita todos os reparse points e symlinks,
        # inclusive internos. Nao atravessa junctions durante buscas.
        cursor = self.root
        for part in parts:
            cursor = cursor / part
            try:
                info = cursor.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise FileSafetyError("Symlink/junction/reparse point bloqueado.")
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                raise FileSafetyError("Arquivo com hard links bloqueado.")
        resolved = candidate.resolve()
        root = os.path.normcase(str(self.root))
        dest = os.path.normcase(str(resolved))
        if os.path.commonpath([root, dest]) != root:
            raise FileSafetyError("Caminho fora do workspace.")
        return candidate


class WriteApproval:
    def __init__(self, ask=input, emit=print):
        self.ask, self.emit = ask, emit
        self.all = False

    def approve(self, path, before, after):
        diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=path + " (antes)", tofile=path + " (depois)"))
        self.emit(diff or f"{path}: normalizacao de codificacao/quebras de linha.")
        if self.all:
            return True
        answer = self.ask("Aplicar escrita? [s]im / [n]ao / [t]odas nesta sessao: ").strip().lower()
        if answer == "t":
            self.all = True
        return answer in {"s", "t"}


def definition(name, description, properties, required):
    return {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}


TEXT = {"type": "string"}
DEFINITIONS = [
    definition("list_directory", "Lista um diretorio relativo; use . para raiz.", {"path": TEXT}, ["path"]),
    definition("read_file", "Le trecho por deslocamento de caracteres; use next_offset para continuar.", {"path": TEXT, "offset": {"type": "integer", "minimum": 0}, "length": {"type": "integer", "minimum": 1, "maximum": 6000}}, ["path"]),
    definition("create_file", "Salva arquivo apos diff e aprovacao; se ja existir, mostra diff de substituicao. VBA usa Windows-1252/CRLF.", {"path": TEXT, "content": TEXT}, ["path", "content"]),
    definition("edit_file", "Substitui uma unica ocorrencia exata de old por new apos aprovacao.", {"path": TEXT, "old": TEXT, "new": TEXT}, ["path", "old", "new"]),
    definition("search_text", "Busca texto literal nos arquivos da pasta, sem seguir links.", {"path": TEXT, "text": TEXT}, ["path", "text"]),
]


class FileTools:
    max_edit_bytes = 2_000_000

    def __init__(self, workspace, approval, output_limit=6000):
        self.workspace, self.approval = workspace, approval
        self.output_limit = output_limit
        self.changed = set()
        self.write_count = 0
        self.refused = False

    def definitions(self, readonly=False):
        return [d for d in DEFINITIONS if not readonly or d["name"] not in {"create_file", "edit_file"}]

    def execute(self, name, arguments):
        if name not in {d["name"] for d in DEFINITIONS}:
            return "ERRO: ferramenta desconhecida."
        try:
            outcome = getattr(self, name)(**arguments)
            if outcome.startswith("RECUSADO"):
                self.refused = True
            return bounded(outcome, self.output_limit)
        except FileSafetyError as error:
            return "ERRO: caminho inseguro: " + str(error)
        except UnicodeEncodeError:
            return "ERRO: caractere nao representavel em Windows-1252; reescreva o arquivo sem esse caractere."
        except UnicodeDecodeError:
            return "ERRO: arquivo existente nao usa a codificacao esperada; nao foi alterado."
        except (OSError, ValueError, TypeError) as error:
            return "ERRO: " + type(error).__name__ + "; revise caminho, permissao, tamanho e argumentos."

    @staticmethod
    def encoding(path):
        return "cp1252" if path.suffix.lower() in {".bas", ".cls"} else "utf-8"

    def list_directory(self, path):
        folder = self.workspace.path(path)
        entries = []
        with os.scandir(folder) as scan:
            for entry in itertools.islice(scan, 201):
                entries.append(entry.name)
        return "\n".join(entries[:200]) + ("\n[SAIDA TRUNCADA: mais de 200 entradas.]" if len(entries) > 200 else "")

    def read_file(self, path, offset=0, length=4000):
        if not 0 <= offset <= 1_000_000 or not 1 <= length <= 6000:
            raise ValueError("Trecho invalido.")
        target = self.workspace.path(path)
        length = min(length, max(1, self.output_limit - 160))
        with target.open("r", encoding=self.encoding(target), newline=None) as file:
            remaining = offset
            while remaining:
                skipped = file.read(min(remaining, 8192))
                if not skipped:
                    break
                remaining -= len(skipped)
            text = file.read(length)
            more = bool(file.read(1))
        return f"offset={offset}; next_offset={offset + len(text)}; mais={more}\n{text}" + ("\n[TRECHO LIMITADO: continue com next_offset.]" if more else "")

    def review_snapshot(self, path, limit):
        target = self.workspace.path(path)
        with target.open("r", encoding=self.encoding(target), newline=None) as file:
            content = file.read(limit + 1)
        if len(content) > limit:
            return content[:limit] + "\n[CONTEUDO TRUNCADO PARA REVISAO]"
        return content

    def create_file(self, path, content):
        target = self.workspace.path(path)
        original = target.read_bytes() if target.exists() else None
        if original is not None and len(original) > self.max_edit_bytes:
            raise ValueError("Arquivo grande demais para substituicao.")
        return self._write(path, content, original)

    def edit_file(self, path, old, new):
        target = self.workspace.path(path)
        if target.stat().st_size > self.max_edit_bytes:
            raise ValueError("Arquivo grande demais para edicao.")
        original = target.read_bytes()
        before = original.decode(self.encoding(target)).replace("\r\n", "\n").replace("\r", "\n")
        old = old.replace("\r\n", "\n").replace("\r", "\n")
        if not old or before.count(old) != 1:
            return "ERRO: old deve corresponder a exatamente uma ocorrencia; leia o trecho e tente novamente."
        return self._write(path, before.replace(old, new, 1), original)

    def _write(self, path, content, original):
        target = self.workspace.path(path)
        if original is None and target.exists():
            return "ERRO: arquivo apareceu durante a operacao; leia e tente novamente."
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        is_vba = target.suffix.lower() in {".bas", ".cls"}
        encoded = (normalized.replace("\n", "\r\n") if is_vba else normalized).encode(self.encoding(target))
        if len(encoded) > self.max_edit_bytes:
            raise ValueError("Conteudo excede limite de edicao.")
        before = "" if original is None else original.decode(self.encoding(target)).replace("\r\n", "\n")
        if not self.approval.approve(path, before, normalized):
            return "RECUSADO pelo usuario. Nenhuma escrita aplicada; nao repita sem nova instrucao."
        target = self.workspace.path(path)
        if original is not None and target.read_bytes() != original:
            return "ERRO: arquivo mudou durante aprovacao; leia novamente."
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self.workspace.path(path)
        with target.open("xb" if original is None else "r+b") as file:
            if original is not None and file.read() != original:
                return "ERRO: arquivo mudou; nenhuma escrita aplicada."
            file.seek(0)
            file.write(encoded)
            file.truncate()
        self.changed.add(path)
        self.write_count += 1
        return "SALVO: " + path

    def search_text(self, path, text):
        if not text:
            raise ValueError("Busca vazia.")
        root = self.workspace.path(path)
        result, scanned = [], 0
        for folder, dirs, files in os.walk(root, followlinks=False):
            safe_dirs = []
            for name in dirs:
                try:
                    self.workspace.path(str((Path(folder) / name).relative_to(self.workspace.root)))
                    safe_dirs.append(name)
                except (OSError, ValueError):
                    pass
            dirs[:] = safe_dirs
            for name in files:
                scanned += 1
                if scanned > 1000:
                    return "\n".join(result) + "\n[SAIDA TRUNCADA: limite de 1000 arquivos.]"
                relative = str((Path(folder) / name).relative_to(self.workspace.root))
                try:
                    target = self.workspace.path(relative)
                    with target.open(encoding=self.encoding(target)) as file:
                        offset, tail = 0, ""
                        while offset < 1_000_000:
                            chunk = file.read(8192)
                            if not chunk:
                                break
                            combined = tail + chunk
                            at = combined.find(text)
                            if at >= 0:
                                result.append(f"{relative}: offset={offset - len(tail) + at}")
                                break
                            tail = combined[-(len(text) - 1):] if len(text) > 1 else ""
                            offset += len(chunk)
                        else:
                            result.append(f"{relative}: [BUSCA TRUNCADA: limite de caracteres]")
                except (OSError, ValueError, UnicodeError):
                    continue
                if len("\n".join(result)) >= self.output_limit:
                    return "\n".join(result) + "\n[SAIDA TRUNCADA]"
        return "\n".join(result) or "Nenhuma ocorrencia em arquivos de texto legiveis."
