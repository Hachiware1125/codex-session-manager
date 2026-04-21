#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SESSION_ID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@dataclass
class LineRecord:
    line_no: int
    raw: str
    data: dict


@dataclass
class JsonlStore:
    path: Path
    rows: list[LineRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class SessionRecord:
    index: int
    session_id: str
    prompt_count: int = 0
    updated_at: datetime | None = None
    title: str = ""
    first_text: str = ""
    last_text: str = ""
    session_files: list[Path] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    full_text: str = ""


@dataclass
class BackupRecord:
    index: int
    path: Path
    created_at: datetime | None
    deleted_session_ids: list[str] = field(default_factory=list)
    moved_session_files: list[Path] = field(default_factory=list)
    backed_up_files: list[Path] = field(default_factory=list)
    item_ref: str = ""


@dataclass
class DeletedRecord:
    index: int
    backup: BackupRecord
    item_index: int
    source: Path
    session_id: str
    preview: str


def codex_dir_from_env() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def clean_text(text: object, limit: int = 120) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit]


def parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    return None


def newer(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def read_jsonl(path: Path, strict: bool = False) -> JsonlStore:
    store = JsonlStore(path=path)
    if not path.exists():
        return store
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                message = f"{path}:{line_no}: invalid JSONL ({exc})"
                if strict:
                    raise SystemExit(message) from exc
                store.errors.append(message)
                continue
            if isinstance(data, dict):
                store.rows.append(LineRecord(line_no=line_no, raw=raw, data=data))
    return store


def ensure_session(sessions: dict[str, SessionRecord], session_id: str) -> SessionRecord:
    item = sessions.get(session_id)
    if item is None:
        item = SessionRecord(index=0, session_id=session_id)
        sessions[session_id] = item
    return item


def add_text(record: SessionRecord, text: str) -> None:
    text = clean_text(text, limit=500)
    if not text:
        return
    if not record.first_text:
        record.first_text = clean_text(text)
    record.last_text = clean_text(text)
    if text not in record.full_text:
        record.full_text = f"{record.full_text}\n{text}".strip()


def text_from_content(content: object) -> str:
    if isinstance(content, str):
        return clean_text(content, limit=1000)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return clean_text(" ".join(parts), limit=1000)


def is_visible_user_prompt(text: str) -> bool:
    ignored_prefixes = (
        "<environment_context>",
        "<permissions instructions>",
        "<app-context>",
        "<collaboration_mode>",
        "<skills_instructions>",
        "<plugins_instructions>",
    )
    return bool(text) and not any(text.startswith(prefix) for prefix in ignored_prefixes)


def extract_id_from_name(path: Path) -> str | None:
    matches = SESSION_ID_RE.findall(path.name)
    if matches:
        return matches[-1].lower()
    return None


def inspect_session_file(path: Path, strict: bool = False) -> tuple[str | None, datetime | None, list[str]]:
    texts: list[str] = []
    session_id = extract_id_from_name(path)
    updated_at: datetime | None = None

    try:
        if path.suffix == ".json":
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                meta = data.get("session")
                if isinstance(meta, dict):
                    session_id = clean_text(meta.get("id")) or session_id
                    updated_at = parse_timestamp(meta.get("timestamp"))
                for item in data.get("items", []):
                    if isinstance(item, dict) and item.get("role") == "user":
                        text = text_from_content(item.get("content"))
                        if is_visible_user_prompt(text):
                            texts.append(text)
        else:
            with path.open("r", encoding="utf-8") as fh:
                for line_no, raw in enumerate(fh, start=1):
                    stripped = raw.strip()
                    if not stripped:
                        continue
                    try:
                        item = json.loads(stripped)
                    except json.JSONDecodeError as exc:
                        if strict:
                            raise SystemExit(f"{path}:{line_no}: invalid JSONL ({exc})") from exc
                        continue
                    if not isinstance(item, dict):
                        continue
                    updated_at = newer(updated_at, parse_timestamp(item.get("timestamp")))
                    if item.get("type") == "session_meta":
                        payload = item.get("payload")
                        if isinstance(payload, dict):
                            session_id = clean_text(payload.get("id")) or session_id
                            updated_at = newer(updated_at, parse_timestamp(payload.get("timestamp")))
                    payload = item.get("payload")
                    if isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") == "user":
                        text = text_from_content(payload.get("content"))
                        if is_visible_user_prompt(text):
                            texts.append(text)
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise SystemExit(f"failed to inspect {path}: {exc}") from exc

    if updated_at is None:
        try:
            updated_at = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            pass
    return session_id, updated_at, texts


def iter_session_files(sessions_dir: Path) -> Iterable[Path]:
    if not sessions_dir.exists():
        return []
    return sorted(
        path
        for path in sessions_dir.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl"}
    )


def load_sessions(codex_dir: Path, strict: bool = False) -> tuple[list[SessionRecord], JsonlStore, JsonlStore]:
    history_store = read_jsonl(codex_dir / "history.jsonl", strict=strict)
    index_store = read_jsonl(codex_dir / "session_index.jsonl", strict=strict)
    sessions: dict[str, SessionRecord] = {}

    for row in history_store.rows:
        session_id = clean_text(row.data.get("session_id"))
        if not session_id:
            continue
        record = ensure_session(sessions, session_id)
        record.sources.add("history")
        record.prompt_count += 1
        record.updated_at = newer(record.updated_at, parse_timestamp(row.data.get("ts")))
        add_text(record, clean_text(row.data.get("text"), limit=1000))

    for row in index_store.rows:
        session_id = clean_text(row.data.get("id"))
        if not session_id:
            continue
        record = ensure_session(sessions, session_id)
        record.sources.add("index")
        record.updated_at = newer(record.updated_at, parse_timestamp(row.data.get("updated_at")))
        title = clean_text(row.data.get("thread_name"))
        if title:
            record.title = title
            if not record.first_text:
                add_text(record, title)

    for path in iter_session_files(codex_dir / "sessions"):
        session_id, updated_at, texts = inspect_session_file(path, strict=strict)
        if not session_id:
            continue
        record = ensure_session(sessions, session_id)
        record.sources.add("file")
        record.session_files.append(path)
        record.updated_at = newer(record.updated_at, updated_at)
        if texts:
            record.prompt_count = max(record.prompt_count, len(texts))
            for text in texts:
                add_text(record, text)

    ordered = sorted(
        sessions.values(),
        key=lambda item: (
            item.updated_at is not None,
            item.updated_at or datetime.fromtimestamp(0),
            item.session_id,
        ),
        reverse=True,
    )
    for index, record in enumerate(ordered, start=1):
        record.index = index
        record.session_files = sorted(set(record.session_files))
    return ordered, history_store, index_store


def filter_sessions(
    sessions: list[SessionRecord],
    query: str | None,
    full_text: bool = False,
) -> list[SessionRecord]:
    if query:
        q = query.lower()
        filtered = []
        for session in sessions:
            haystack = [
                session.session_id,
                session.title,
                session.first_text,
                session.last_text,
            ]
            if full_text:
                haystack.append(session.full_text)
            if any(q in item.lower() for item in haystack if item):
                filtered.append(session)
        sessions = filtered
    return [
        SessionRecord(
            index=index,
            session_id=session.session_id,
            prompt_count=session.prompt_count,
            updated_at=session.updated_at,
            title=session.title,
            first_text=session.first_text,
            last_text=session.last_text,
            session_files=session.session_files,
            sources=session.sources,
            full_text=session.full_text,
        )
        for index, session in enumerate(sessions, start=1)
    ]


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M")


def backup_dir(codex_dir: Path) -> Path:
    return codex_dir / "history_backups"


def load_backup_manifest(path: Path) -> dict:
    manifest_path = path / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"invalid manifest: {manifest_path}")
    return data


def iter_backups(codex_dir: Path) -> list[BackupRecord]:
    root = backup_dir(codex_dir)
    if not root.exists():
        return []

    records: list[BackupRecord] = []
    for path in sorted(root.glob("session-delete-*")):
        if not path.is_dir() or not (path / "manifest.json").exists():
            continue
        try:
            manifest = load_backup_manifest(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        deleted_ids = [
            clean_text(item)
            for item in manifest.get("deleted_session_ids", [])
            if clean_text(item)
        ]
        moved_files = [
            Path(item)
            for item in manifest.get("moved_session_files", [])
            if isinstance(item, str)
        ]
        backed_up_files = [
            Path(item)
            for item in manifest.get("backed_up_files", [])
            if isinstance(item, str)
        ]
        records.append(
            BackupRecord(
                index=0,
                path=path,
                created_at=parse_timestamp(manifest.get("created_at")),
                deleted_session_ids=deleted_ids,
                moved_session_files=moved_files,
                backed_up_files=backed_up_files,
            )
        )

    records.sort(
        key=lambda item: (
            item.created_at is not None,
            item.created_at or datetime.fromtimestamp(0),
            item.path.name,
        ),
        reverse=True,
    )
    for index, record in enumerate(records, start=1):
        record.index = index
    return records


def resolve_backup(codex_dir: Path, ref: str) -> BackupRecord:
    backups = iter_backups(codex_dir)
    if ref.isdigit():
        index = int(ref)
        for backup in backups:
            if backup.index == index:
                return backup
        raise ValueError(f"backup index out of range: {ref}")

    candidate = Path(ref).expanduser()
    if not candidate.is_absolute():
        candidate = backup_dir(codex_dir) / ref
    candidate = candidate.resolve()

    backups_by_path = {backup.path.resolve(): backup for backup in backups}
    if candidate in backups_by_path:
        return backups_by_path[candidate]
    raise ValueError(f"backup not found: {ref}")


def resolve_backup_item(codex_dir: Path, ref: str) -> BackupRecord:
    if "." not in ref:
        raise ValueError("deleted item must use BACKUP.ITEM format, e.g. 1.2")
    backup_ref, item_ref = ref.split(".", 1)
    if not item_ref.isdigit():
        raise ValueError(f"invalid deleted item index: {ref}")
    backup = resolve_backup(codex_dir, backup_ref)
    item_index = int(item_ref)
    if item_index < 1 or item_index > len(backup.moved_session_files):
        raise ValueError(f"deleted item index out of range: {ref}")
    moved_file = backup.moved_session_files[item_index - 1]
    session_id, _ = preview_deleted_file(moved_file)
    deleted_ids = [] if session_id == "-" else [session_id]
    return BackupRecord(
        index=backup.index,
        path=backup.path,
        created_at=backup.created_at,
        deleted_session_ids=deleted_ids,
        moved_session_files=[moved_file],
        backed_up_files=backup.backed_up_files,
        item_ref=ref,
    )


def resolve_restore_ref(codex_dir: Path, ref: str) -> BackupRecord:
    if "." in ref:
        return resolve_backup_item(codex_dir, ref)
    return resolve_backup(codex_dir, ref)


def preview_deleted_file(path: Path, strict: bool = False) -> tuple[str, str]:
    session_id, _, texts = inspect_session_file(path, strict=strict)
    preview = clean_text(texts[-1] if texts else path.name)
    return session_id or extract_id_from_name(path) or "-", preview or "(no prompt text)"


def build_deleted_records(backups: list[BackupRecord], strict: bool = False) -> list[DeletedRecord]:
    records: list[DeletedRecord] = []
    for backup in backups:
        for item_index, path in enumerate(backup.moved_session_files, start=1):
            session_id, preview = preview_deleted_file(path, strict=strict)
            records.append(
                DeletedRecord(
                    index=0,
                    backup=backup,
                    item_index=item_index,
                    source=path,
                    session_id=session_id,
                    preview=preview,
                )
            )
    for index, record in enumerate(records, start=1):
        record.index = index
    return records


def deleted_record_ref(record: DeletedRecord) -> str:
    return f"{record.backup.index}.{record.item_index}"


def backup_from_deleted_record(record: DeletedRecord) -> BackupRecord:
    deleted_ids = [] if record.session_id == "-" else [record.session_id]
    return BackupRecord(
        index=record.backup.index,
        path=record.backup.path,
        created_at=record.backup.created_at,
        deleted_session_ids=deleted_ids,
        moved_session_files=[record.source],
        backed_up_files=record.backup.backed_up_files,
        item_ref=f"{record.index} (backup {deleted_record_ref(record)})",
    )


def resolve_deleted_record(codex_dir: Path, ref: str, strict: bool = False) -> DeletedRecord:
    records = build_deleted_records(iter_backups(codex_dir), strict=strict)
    if not ref.isdigit():
        raise ValueError(f"deleted conversation index must be a number: {ref}")
    index = int(ref)
    for record in records:
        if record.index == index:
            return record
    raise ValueError(f"deleted conversation index out of range: {ref}")


def print_backups(backups: list[BackupRecord]) -> None:
    if not backups:
        print("No deletion backups found.")
        return
    print("Index  Created           Sessions  Files  Backup Directory")
    print("-----  ----------------  --------  -----  ----------------")
    for backup in backups:
        print(
            f"{backup.index:>5}  {fmt_ts(backup.created_at):<16}  "
            f"{len(backup.deleted_session_ids):>8}  {len(backup.moved_session_files):>5}  {backup.path}"
        )
    print(f"\nDisplayed all {len(backups)} deletion backup(s).")


def print_deleted_conversations(backups: list[BackupRecord], strict: bool = False) -> None:
    rows = build_deleted_records(backups, strict=strict)

    if not rows:
        print("No deleted conversations found in backups.")
        return

    print("Index  Deleted At        Backup.Item  Preview")
    print("-----  ----------------  -----------  -------")
    for record in rows:
        print(
            f"{record.index:>5}  {fmt_ts(record.backup.created_at):<16}  "
            f"{deleted_record_ref(record):<11}  {record.preview}"
        )
    print(f"\nDisplayed all {len(rows)} deleted conversation(s) from {len(backups)} backup(s).")


def print_warnings(stores: Iterable[JsonlStore]) -> None:
    for store in stores:
        for error in store.errors:
            print(f"Warning: {error}", file=sys.stderr)


def print_sessions(sessions: list[SessionRecord], show_id: bool = False) -> None:
    if not sessions:
        print("No matching Codex sessions found.")
        return
    if show_id:
        print("Index  Updated           Prompts  Sources       Session ID                             Preview")
        print("-----  ----------------  -------  ------------  ------------------------------------  -------")
    else:
        print("Index  Updated           Prompts  Sources       Preview")
        print("-----  ----------------  -------  ------------  -------")
    for session in sessions:
        preview = session.last_text or session.first_text or session.title or "(no prompt text)"
        sources = ",".join(sorted(session.sources)) or "-"
        prefix = (
            f"{session.index:>5}  {fmt_ts(session.updated_at):<16}  "
            f"{session.prompt_count:>7}  {sources:<12}  "
        )
        if show_id:
            print(f"{prefix}{session.session_id:<36}  {preview}")
        else:
            print(f"{prefix}{preview}")
    print(f"\nDisplayed all {len(sessions)} conversation(s).")


def validate_index(value: int, max_index: int) -> None:
    if value < 1 or value > max_index:
        raise ValueError(f"index out of range: {value}")


def parse_selection(selection: str, max_index: int) -> list[int]:
    chosen: set[int] = set()
    for part in selection.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_s, end_s = token.split("-", 1)
            start = int(start_s)
            end = int(end_s)
            if start > end:
                start, end = end, start
            for value in range(start, end + 1):
                validate_index(value, max_index)
                chosen.add(value)
        else:
            value = int(token)
            validate_index(value, max_index)
            chosen.add(value)
    return sorted(chosen)


def select_sessions(
    sessions: list[SessionRecord],
    indexes: str | None,
    session_ids: str | None,
) -> list[SessionRecord]:
    selected: dict[str, SessionRecord] = {}
    if indexes:
        for index in parse_selection(indexes, len(sessions)):
            session = sessions[index - 1]
            selected[session.session_id] = session
    if session_ids:
        wanted = {item.strip() for item in session_ids.split(",") if item.strip()}
        by_id = {session.session_id: session for session in sessions}
        missing = sorted(wanted - set(by_id))
        if missing:
            raise ValueError(f"session id not found in current list: {', '.join(missing)}")
        for session_id in wanted:
            selected[session_id] = by_id[session_id]
    return sorted(selected.values(), key=lambda item: item.index)


def copy_if_exists(path: Path, backup_root: Path, codex_dir: Path) -> Path | None:
    if not path.exists():
        return None
    relative = path.relative_to(codex_dir)
    target = backup_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def atomic_write_jsonl(path: Path, rows: list[LineRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(row.raw if row.raw.endswith("\n") else f"{row.raw}\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class LockFile:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> "LockFile":
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, f"{os.getpid()}\n".encode("utf-8"))
        except FileExistsError as exc:
            raise SystemExit(f"lock exists: {self.path}") from exc
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


def delete_sessions(
    codex_dir: Path,
    selected: list[SessionRecord],
    history_store: JsonlStore,
    index_store: JsonlStore,
    dry_run: bool = False,
) -> None:
    selected_ids = {item.session_id for item in selected}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = codex_dir / "history_backups" / f"session-delete-{stamp}"

    print("\nSelected sessions:")
    for item in selected:
        preview = item.last_text or item.first_text or item.title or "(no prompt text)"
        print(f"  [{item.index}] {item.session_id}  {preview}")

    session_files = sorted({path for item in selected for path in item.session_files})
    history_rows = [row for row in history_store.rows if clean_text(row.data.get("session_id")) in selected_ids]
    index_rows = [row for row in index_store.rows if clean_text(row.data.get("id")) in selected_ids]

    print("\nPlanned changes:")
    print(f"  backup directory: {backup_root}")
    print(f"  history rows removed: {len(history_rows)}")
    print(f"  index rows removed: {len(index_rows)}")
    print(f"  session files moved: {len(session_files)}")
    for path in session_files:
        print(f"    {path}")

    if dry_run:
        print("\nDry run only. No files changed.")
        return

    backup_root.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in [history_store.path, index_store.path]:
        target = copy_if_exists(source, backup_root, codex_dir)
        if target:
            copied.append(target)

    moved = []
    for source in session_files:
        if not source.exists():
            continue
        target = backup_root / source.relative_to(codex_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(target)

    kept_history = [
        row for row in history_store.rows if clean_text(row.data.get("session_id")) not in selected_ids
    ]
    kept_index = [row for row in index_store.rows if clean_text(row.data.get("id")) not in selected_ids]
    if history_store.path.exists():
        atomic_write_jsonl(history_store.path, kept_history)
    if index_store.path.exists():
        atomic_write_jsonl(index_store.path, kept_index)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "codex_dir": str(codex_dir),
        "deleted_session_ids": sorted(selected_ids),
        "backed_up_files": [str(path) for path in copied],
        "moved_session_files": [str(path) for path in moved],
    }
    with (backup_root / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"\nBackup created: {backup_root}")
    print(f"Deleted {len(selected)} session(s). Session files were moved into the backup directory.")


def backup_jsonl_path(backup: BackupRecord, name: str) -> Path:
    for path in backup.backed_up_files:
        if path.name == name:
            return path
    return backup.path / name


def restore_jsonl_rows(
    current_path: Path,
    backup_path: Path,
    key_field: str,
    selected_ids: set[str],
    dry_run: bool = False,
) -> int:
    if not backup_path.exists():
        return 0

    current_store = read_jsonl(current_path)
    backup_store = read_jsonl(backup_path)
    current_raw = {row.raw.strip() for row in current_store.rows}
    restored = [
        row
        for row in backup_store.rows
        if clean_text(row.data.get(key_field)) in selected_ids and row.raw.strip() not in current_raw
    ]

    if restored and not dry_run:
        atomic_write_jsonl(current_path, current_store.rows + restored)
    return len(restored)


def restore_backup(codex_dir: Path, backup: BackupRecord, dry_run: bool = False) -> None:
    selected_ids = set(backup.deleted_session_ids)

    print("\nSelected backup:")
    print(f"  [{backup.index}] {backup.path}")
    print(f"  created: {fmt_ts(backup.created_at)}")

    print("\nDeleted conversations in backup:")
    for item_index, path in enumerate(backup.moved_session_files, start=1):
        _, preview = preview_deleted_file(path)
        label = backup.item_ref or f"{backup.index}.{item_index}"
        print(f"  [{label}] {preview}")

    restore_pairs: list[tuple[Path, Path, str]] = []
    for source in backup.moved_session_files:
        if not source.exists():
            restore_pairs.append((source, codex_dir / source.relative_to(backup.path), "missing backup file"))
            continue
        target = codex_dir / source.relative_to(backup.path)
        status = "exists, skip" if target.exists() else "restore"
        restore_pairs.append((source, target, status))

    history_count = restore_jsonl_rows(
        codex_dir / "history.jsonl",
        backup_jsonl_path(backup, "history.jsonl"),
        "session_id",
        selected_ids,
        dry_run=True,
    )
    index_count = restore_jsonl_rows(
        codex_dir / "session_index.jsonl",
        backup_jsonl_path(backup, "session_index.jsonl"),
        "id",
        selected_ids,
        dry_run=True,
    )

    print("\nPlanned restore:")
    print(f"  backup retained: {backup.path}")
    print(f"  session files restored: {sum(1 for _, _, status in restore_pairs if status == 'restore')}")
    print(f"  history rows restored: {history_count}")
    print(f"  index rows restored: {index_count}")
    for source, target, status in restore_pairs:
        print(f"    {status}: {source} -> {target}")

    if dry_run:
        print("\nDry run only. No files changed.")
        return

    for source, target, status in restore_pairs:
        if status != "restore":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    restored_history = restore_jsonl_rows(
        codex_dir / "history.jsonl",
        backup_jsonl_path(backup, "history.jsonl"),
        "session_id",
        selected_ids,
        dry_run=False,
    )
    restored_index = restore_jsonl_rows(
        codex_dir / "session_index.jsonl",
        backup_jsonl_path(backup, "session_index.jsonl"),
        "id",
        selected_ids,
        dry_run=False,
    )

    print("\nRestore complete.")
    print(f"Restored session files: {sum(1 for _, _, status in restore_pairs if status == 'restore')}")
    print(f"Restored history rows: {restored_history}")
    print(f"Restored index rows: {restored_index}")
    print(f"Backup retained: {backup.path}")


def purge_backup(backup: BackupRecord, dry_run: bool = False) -> None:
    files = [path for path in backup.path.rglob("*") if path.is_file()]

    print("\nSelected backup:")
    print(f"  [{backup.index}] {backup.path}")
    print(f"  created: {fmt_ts(backup.created_at)}")

    print("\nPlanned purge:")
    print(f"  backup directory removed: {backup.path}")
    print(f"  files removed: {len(files)}")
    for path in files:
        print(f"    {path}")

    if dry_run:
        print("\nDry run only. No files changed.")
        return

    shutil.rmtree(backup.path)
    print(f"\nPurged backup: {backup.path}")


def purge_deleted_item(backup: BackupRecord, dry_run: bool = False) -> None:
    source = backup.moved_session_files[0]
    session_id, preview = preview_deleted_file(source)

    print("\nSelected deleted conversation:")
    print(f"  item: [{backup.item_ref}]")
    print(f"  backup: [{backup.index}] {backup.path}")
    print(f"  preview: {preview}")

    print("\nPlanned purge:")
    print(f"  session file removed: {source}")
    print("  manifest updated: yes")

    if dry_run:
        print("\nDry run only. No files changed.")
        return

    if source.exists():
        source.unlink()

    manifest = load_backup_manifest(backup.path)
    moved_files = [
        item
        for item in manifest.get("moved_session_files", [])
        if isinstance(item, str) and Path(item) != source
    ]
    deleted_ids = [
        item
        for item in manifest.get("deleted_session_ids", [])
        if clean_text(item) and clean_text(item) != session_id
    ]
    manifest["moved_session_files"] = moved_files
    manifest["deleted_session_ids"] = deleted_ids
    with (backup.path / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"\nPurged deleted conversation from backup: {preview}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List, search, and safely delete local Codex session history."
    )
    parser.add_argument("--codex-dir", type=Path, default=codex_dir_from_env(), help="Codex data directory.")
    parser.add_argument("--list", action="store_true", help="List sessions in a table with Index as the first column.")
    parser.add_argument("--list-deleted", action="store_true", help="List deleted conversations stored in backups.")
    parser.add_argument("--list-backups", action="store_true", help="List deletion backup batches.")
    parser.add_argument("--show-id", action="store_true", help="Include stable session ids in list output.")
    parser.add_argument("--search", metavar="TEXT", help="Filter sessions by preview, title, or id.")
    parser.add_argument("--full-text", action="store_true", help="Search parsed session-file text too.")
    parser.add_argument("--delete", metavar="INDEXES", help="Delete index selection, e.g. 3 or 2,5-7.")
    parser.add_argument("--delete-id", metavar="IDS", help="Delete comma-separated session ids.")
    parser.add_argument("--restore", metavar="BACKUP", help="Restore a backup or deleted item by index, name, or path.")
    parser.add_argument("--restore-deleted", metavar="INDEX", help="Restore one deleted conversation by list-deleted index.")
    parser.add_argument("--purge-backup", metavar="BACKUP", help="Permanently delete a backup by index, name, or path.")
    parser.add_argument("--purge-deleted", metavar="INDEX", help="Permanently delete one deleted conversation by list-deleted index or BACKUP.ITEM.")
    parser.add_argument("--dry-run", action="store_true", help="Show the planned changes without changing files.")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    parser.add_argument("--strict", action="store_true", help="Fail on malformed JSONL or unreadable session files.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    codex_dir = args.codex_dir.expanduser().resolve()

    if args.list_backups:
        print_backups(iter_backups(codex_dir))
        return 0

    if args.list_deleted:
        print_deleted_conversations(iter_backups(codex_dir), strict=args.strict)
        return 0

    if args.restore_deleted:
        try:
            record = resolve_deleted_record(codex_dir, args.restore_deleted, strict=args.strict)
            backup = backup_from_deleted_record(record)
        except ValueError as exc:
            print(f"Invalid deleted conversation: {exc}", file=sys.stderr)
            return 1
        context = LockFile(codex_dir / ".codex-session-manager.lock") if not args.dry_run else NullContext()
        with context:
            restore_backup(codex_dir, backup, dry_run=args.dry_run)
        if not args.dry_run:
            refreshed, _, _ = load_sessions(codex_dir, strict=False)
            print("\nUpdated session list:")
            print_sessions(refreshed, show_id=args.show_id)
            print("Indexes may have shifted after restore.")
        return 0

    if args.restore:
        try:
            backup = resolve_restore_ref(codex_dir, args.restore)
        except ValueError as exc:
            print(f"Invalid backup: {exc}", file=sys.stderr)
            return 1
        context = LockFile(codex_dir / ".codex-session-manager.lock") if not args.dry_run else NullContext()
        with context:
            restore_backup(codex_dir, backup, dry_run=args.dry_run)
        if not args.dry_run:
            refreshed, _, _ = load_sessions(codex_dir, strict=False)
            print("\nUpdated session list:")
            print_sessions(refreshed, show_id=args.show_id)
            print("Indexes may have shifted after restore.")
        return 0

    if args.purge_deleted:
        try:
            if "." in args.purge_deleted:
                backup = resolve_backup_item(codex_dir, args.purge_deleted)
            else:
                record = resolve_deleted_record(codex_dir, args.purge_deleted, strict=args.strict)
                backup = backup_from_deleted_record(record)
        except ValueError as exc:
            print(f"Invalid deleted item: {exc}", file=sys.stderr)
            return 1
        if not args.dry_run and not args.yes:
            purge_deleted_item(backup, dry_run=True)
            confirm = input("\nPermanently delete this deleted conversation backup? [y/N]: ").strip().lower()
            if confirm not in {"y", "yes"}:
                print("Cancelled.")
                return 0
        context = LockFile(codex_dir / ".codex-session-manager.lock") if not args.dry_run else NullContext()
        with context:
            purge_deleted_item(backup, dry_run=args.dry_run)
        return 0

    if args.purge_backup:
        try:
            backup = resolve_backup(codex_dir, args.purge_backup)
        except ValueError as exc:
            print(f"Invalid backup: {exc}", file=sys.stderr)
            return 1
        if not args.dry_run and not args.yes:
            purge_backup(backup, dry_run=True)
            confirm = input("\nPermanently delete this backup? [y/N]: ").strip().lower()
            if confirm not in {"y", "yes"}:
                print("Cancelled.")
                return 0
        context = LockFile(codex_dir / ".codex-session-manager.lock") if not args.dry_run else NullContext()
        with context:
            purge_backup(backup, dry_run=args.dry_run)
        return 0

    all_sessions, history_store, index_store = load_sessions(codex_dir, strict=args.strict)
    print_warnings([history_store, index_store])
    sessions = filter_sessions(all_sessions, args.search, full_text=args.full_text)

    if not sessions:
        print("No matching Codex sessions found.")
        return 0

    print_sessions(sessions, show_id=args.show_id)

    if args.list and not args.delete and not args.delete_id:
        return 0

    if args.delete or args.delete_id:
        try:
            selected = select_sessions(sessions, args.delete, args.delete_id)
        except ValueError as exc:
            print(f"Invalid selection: {exc}", file=sys.stderr)
            return 1
    else:
        selection = input("\nEnter session index to delete (e.g. 3 or 2,5-7), or press Enter to cancel: ").strip()
        if not selection:
            print("Cancelled.")
            return 0
        try:
            selected = select_sessions(sessions, selection, None)
        except ValueError as exc:
            print(f"Invalid selection: {exc}", file=sys.stderr)
            return 1

    if not selected:
        print("No sessions selected.")
        return 0

    if not args.dry_run and not args.yes:
        print("\nSelected sessions:")
        for item in selected:
            preview = item.last_text or item.first_text or item.title or "(no prompt text)"
            print(f"  [{item.index}] {item.session_id}  {preview}")
        confirm = input("\nDelete these session(s)? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    context = LockFile(codex_dir / ".codex-session-manager.lock") if not args.dry_run else NullContext()
    with context:
        delete_sessions(codex_dir, selected, history_store, index_store, dry_run=args.dry_run)

    if not args.dry_run:
        refreshed, _, _ = load_sessions(codex_dir, strict=False)
        refreshed = filter_sessions(refreshed, args.search, full_text=args.full_text)
        print("\nUpdated session list:")
        print_sessions(refreshed, show_id=args.show_id)
        print("Indexes may have shifted after deletion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
