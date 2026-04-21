---
name: "codex-session-manager"
description: "Use when the user wants to list, inspect, search, safely delete, restore, or permanently purge local Codex conversation history, old chats, session records, deletion backups, or session files on this machine. Use the bundled session manager script to show sessions as an indexed table, combine history.jsonl, session_index.jsonl, and sessions/ data, protect deletions with dry runs, confirmation, backups, and current-list indexes, and manage deletion backups for recovery or permanent removal."
---

# Codex Session Manager

## Core Interaction
- The primary output is a table of local Codex conversations.
- The first column is `Index`; it is the current-list number users can refer to, such as "delete index 3" or "show 2,5-7".
- Do not show `Session ID` in the default table. Use `--show-id` only when the user needs a stable id or asks for exact identifiers.
- The table ends with a total count so the user can tell that all matching conversations were displayed.
- Always show or refresh the table before acting on an index.
- Treat `Index` values as temporary. They are valid only for the latest displayed table with the same search filters.
- Use `Session ID` as the stable alternative when precision matters.
- Deletion backups have their own `Index` from `--list-backups`; backup indexes are separate from conversation indexes.
- Deleted conversations also have their own `Index` from `--list-deleted`; use that index with `--restore-deleted` or `--purge-deleted`.

## Workflow
1. Use the bundled script for deterministic session operations.
   - Run commands from this skill folder:
   ```bash
   python3 scripts/delete_codex_session.py --list
   ```
2. List before selecting sessions.
   - The list is printed as a table whose first column is `Index`.
   - Treat indexes as ephemeral; they only refer to the latest displayed table.
   - If the user gives a keyword, filter first:
   ```bash
   python3 scripts/delete_codex_session.py --list --search "<keyword>"
   ```
3. Prefer stable ids for deletion when the user has identified a session id.
   - If the id is not visible, rerun the relevant list with `--show-id`.
   ```bash
   python3 scripts/delete_codex_session.py --delete-id "<session-id>" --dry-run
   ```
4. Use `--dry-run` before destructive operations unless the user has already asked for a specific deletion.
   ```bash
   python3 scripts/delete_codex_session.py --delete 3 --dry-run
   ```
5. Delete only after clearly restating the selected session preview and backup plan.
   ```bash
   python3 scripts/delete_codex_session.py --delete 3 --yes
   ```
6. After deletion, show the refreshed list and remind the user that indexes may have shifted.
7. To inspect deleted conversations, list deletion backups or deleted items:
   ```bash
   python3 scripts/delete_codex_session.py --list-backups
   python3 scripts/delete_codex_session.py --list-deleted
   ```
8. Restore a backup or one deleted conversation directly when the user clearly asks for restoration.
   - A prior `--dry-run` is optional, not mandatory.
   - Do not ask for a second confirmation for restore commands.
   ```bash
   python3 scripts/delete_codex_session.py --restore 1
   python3 scripts/delete_codex_session.py --restore-deleted 2
   ```
9. Permanently purge one deleted conversation or a whole backup only after a dry run and explicit confirmation:
   ```bash
   python3 scripts/delete_codex_session.py --purge-deleted 2 --dry-run
   python3 scripts/delete_codex_session.py --purge-deleted 2 --yes
   python3 scripts/delete_codex_session.py --purge-backup 1 --dry-run
   python3 scripts/delete_codex_session.py --purge-backup 1 --yes
   ```

## Script Behavior
- `scripts/delete_codex_session.py` merges sessions from:
  - `~/.codex/history.jsonl`
  - `~/.codex/session_index.jsonl`
  - `~/.codex/sessions/**/*.json`
  - `~/.codex/sessions/**/*.jsonl`
- Deletion removes matching rows from `history.jsonl` and `session_index.jsonl`.
- Matching session files are moved into a timestamped backup directory instead of being unlinked.
- Backups are written under `~/.codex/history_backups/session-delete-<timestamp>/`.
- `manifest.json` records deleted ids and moved files for recovery.
- `--list-deleted` reads backup manifests and shows deleted conversation previews with an `Index` column for direct selection.
- `--restore` copies a whole backup back to original paths. `--restore-deleted` restores one deleted conversation by `--list-deleted` index.
- `--purge-deleted` permanently removes one deleted conversation by `--list-deleted` index. It also accepts legacy `BACKUP.ITEM` refs.
- `--purge-backup` permanently removes an entire deletion backup directory.
- JSONL writes use a temporary file and atomic replace.
- A lock file prevents concurrent delete operations.

## Commands
List:
```bash
python3 scripts/delete_codex_session.py --list
```

Search by preview, title, or id:
```bash
python3 scripts/delete_codex_session.py --list --search "<keyword>"
```

Search parsed session-file text too:
```bash
python3 scripts/delete_codex_session.py --list --search "<keyword>" --full-text
```

Show stable session ids when needed:
```bash
python3 scripts/delete_codex_session.py --list --show-id
```

Preview deletion by current-list index:
```bash
python3 scripts/delete_codex_session.py --delete 2,5-7 --dry-run
```

Delete by stable session id:
```bash
python3 scripts/delete_codex_session.py --delete-id "<session-id>" --yes
```

List deletion backup batches:
```bash
python3 scripts/delete_codex_session.py --list-backups
```

List deleted conversations stored in backups:
```bash
python3 scripts/delete_codex_session.py --list-deleted
```

Restore a backup:
```bash
python3 scripts/delete_codex_session.py --restore 1
```

Restore one deleted conversation:
```bash
python3 scripts/delete_codex_session.py --restore-deleted 2
```

Preview and permanently delete one deleted conversation:
```bash
python3 scripts/delete_codex_session.py --purge-deleted 2 --dry-run
python3 scripts/delete_codex_session.py --purge-deleted 2 --yes
```

Preview and permanently delete a whole backup:
```bash
python3 scripts/delete_codex_session.py --purge-backup 1 --dry-run
python3 scripts/delete_codex_session.py --purge-backup 1 --yes
```

Use a non-default Codex data directory:
```bash
python3 scripts/delete_codex_session.py --codex-dir /path/to/.codex --list
```

## Safety Rules
- Never guess an index. Always rerun the relevant list before deleting.
- If an index came from a filtered list, include the same `--search` and `--full-text` flags in the deletion command or use `--delete-id`.
- Prefer `--delete-id` when the user names or pastes a session id.
- Use `--dry-run` to show planned history rows, index rows, session files, and backup directory.
- For restore operations, do not ask for another confirmation when the user clearly selected a backup or deleted-conversation index.
- Use `--dry-run` before `--purge-deleted` and `--purge-backup`.
- Use `--purge-deleted` for one deleted conversation and `--purge-backup` only when the entire backup is no longer needed.
- Always run `--list-deleted` before acting on a deleted-conversation index.
- Never run `--purge-backup --yes` unless the user explicitly confirms permanent deletion of that backup.
- Never run `--purge-deleted --yes` unless the user explicitly confirms permanent deletion of that deleted conversation backup.
- Do not manually edit `history.jsonl`, `session_index.jsonl`, or files under `sessions/` if the script can do the job.
- If the script reports malformed JSONL, rerun with `--strict` only when you want it to fail instead of skipping bad lines.

## Open Source Notes
- Keep runtime logic in `scripts/delete_codex_session.py`; keep `SKILL.md` concise and procedural.
- Do not depend on local wrappers or machine-specific paths in the portable skill contract.
- Before publishing, remove local-only files and verify:
```bash
python3 scripts/delete_codex_session.py --help
python3 scripts/delete_codex_session.py --list
python3 scripts/delete_codex_session.py --search skill --dry-run --delete 1
python3 scripts/delete_codex_session.py --list-backups
python3 scripts/delete_codex_session.py --list-deleted
python3 scripts/delete_codex_session.py --restore-deleted 1
python3 scripts/delete_codex_session.py --purge-deleted 1 --dry-run
python3 /path/to/skill-creator/scripts/quick_validate.py .
```

## Final Checks
- Confirm the list includes sessions from `history`, `index`, and `file` sources when those data exist.
- Confirm dry run makes no filesystem changes.
- Confirm destructive deletion creates a timestamped backup with `manifest.json`.
- Confirm backup listing, direct restore, and purge dry run work after a deletion.
- Confirm the refreshed list is shown after deletion.
