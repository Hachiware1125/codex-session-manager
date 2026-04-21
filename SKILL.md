---
name: "codex-session-manager"
description: "Use when the user wants to list, inspect, search, or safely delete local Codex conversation history, old chats, session records, or session files on this machine. Use the bundled session manager script to combine history.jsonl, session_index.jsonl, and sessions/ data; protect deletions with dry runs, confirmation, backups, and current-list indexes."
---

# Codex Session Manager

## Workflow
1. Use the bundled script for deterministic session operations.
   - Run commands from this skill folder:
   ```bash
   python3 scripts/delete_codex_session.py --list
   ```
2. List before selecting sessions.
   - Treat indexes as ephemeral; they only refer to the latest displayed list.
   - If the user gives a keyword, filter first:
   ```bash
   python3 scripts/delete_codex_session.py --list --search "<keyword>"
   ```
3. Prefer stable ids for deletion when the user has identified a session id.
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

Preview deletion by current-list index:
```bash
python3 scripts/delete_codex_session.py --delete 2,5-7 --dry-run
```

Delete by stable session id:
```bash
python3 scripts/delete_codex_session.py --delete-id "<session-id>" --yes
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
python3 /path/to/skill-creator/scripts/quick_validate.py .
```

## Final Checks
- Confirm the list includes sessions from `history`, `index`, and `file` sources when those data exist.
- Confirm dry run makes no filesystem changes.
- Confirm destructive deletion creates a timestamped backup with `manifest.json`.
- Confirm the refreshed list is shown after deletion.
