# Codex Session Manager

历史对话管理：a Codex skill and CLI utility for listing, searching, safely deleting, restoring, and permanently purging local Codex conversation history.

It turns local Codex session files into readable indexed tables, so you can choose conversations by `Index` instead of copying long session ids. Deletions are conservative by default: selected sessions are moved into timestamped backups, and deleted conversations can be listed and restored later.

## Highlights

- Lists all local Codex conversations in an indexed table
- Hides stable session ids by default to keep the table readable
- Searches by preview, title, session id, and optional full session text
- Deletes by current table index or stable session id
- Moves deleted session files into timestamped backups
- Lists deleted conversations with their own `Index`
- Restores one deleted conversation or an entire deletion backup
- Permanently purges one deleted conversation backup or an entire backup batch
- Uses dry runs, confirmation gates, backups, atomic JSONL writes, and a lock file for safer operations
- Has no third-party Python runtime dependencies

## Data Sources

By default, the script reads from `~/.codex`, or from `$CODEX_HOME` when that environment variable is set.

It combines session information from:

- `history.jsonl`
- `session_index.jsonl`
- `sessions/**/*.json`
- `sessions/**/*.jsonl`

## Requirements

- Python 3.10 or newer
- macOS, Linux, or another environment with a local Codex data directory
- No third-party Python packages

## Installation As A Codex Skill

Clone this repository into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/Hachiware1125/codex-session-manager.git ~/.codex/skills/codex-session-manager
```

Then ask Codex to use `codex-session-manager` when you want to inspect, clean up, restore, or permanently purge local Codex conversations.

## Quick Start

Run commands from the repository directory:

```bash
cd ~/.codex/skills/codex-session-manager
```

List current conversations:

```bash
python3 scripts/delete_codex_session.py --list
```

Example output:

```text
Index  Updated           Prompts  Sources       Preview
-----  ----------------  -------  ------------  -------
    1  2026-04-22 07:25       37  file,index    Example conversation preview

Displayed all 1 conversation(s).
```

Search current conversations:

```bash
python3 scripts/delete_codex_session.py --list --search "keyword"
```

Search parsed session-file text too:

```bash
python3 scripts/delete_codex_session.py --list --search "keyword" --full-text
```

Show stable session ids when you need exact identifiers:

```bash
python3 scripts/delete_codex_session.py --list --show-id
```

## Delete Conversations

Always list or search immediately before deleting by index. Indexes are valid only for the latest displayed table.

Preview deletion by current table index:

```bash
python3 scripts/delete_codex_session.py --delete 3 --dry-run
```

Preview deletion by multiple indexes or ranges:

```bash
python3 scripts/delete_codex_session.py --delete 2,5-7 --dry-run
```

Delete after confirming the dry-run plan:

```bash
python3 scripts/delete_codex_session.py --delete 2,5-7 --yes
```

Delete by stable session id:

```bash
python3 scripts/delete_codex_session.py --delete-id "00000000-0000-0000-0000-000000000000" --yes
```

Deletion moves session files into a backup directory instead of unlinking them immediately:

```text
~/.codex/history_backups/session-delete-<timestamp>/
```

## Deleted Conversations

List deletion backup batches:

```bash
python3 scripts/delete_codex_session.py --list-backups
```

List deleted conversations:

```bash
python3 scripts/delete_codex_session.py --list-deleted
```

Example output:

```text
Index  Deleted At        Backup.Item  Preview
-----  ----------------  -----------  -------
    1  2026-04-21 23:54  1.1          Example deleted conversation

Displayed all 1 deleted conversation(s) from 1 backup(s).
```

Use the first `Index` column for restore or purge operations. `Backup.Item` is kept only for traceability.

## Restore

Restore one deleted conversation by deleted-list index:

```bash
python3 scripts/delete_codex_session.py --restore-deleted 1
```

Restore an entire deletion backup batch:

```bash
python3 scripts/delete_codex_session.py --restore 1
```

Restore operations do not ask for a second confirmation when you already selected a backup or deleted-conversation index. They copy moved session files back to their original paths and restore matching `history.jsonl` or `session_index.jsonl` rows when possible.

The backup directory is retained after restore.

## Permanent Purge

Permanent purge removes backup files and cannot be recovered through this skill.

Preview permanent purge of one deleted conversation:

```bash
python3 scripts/delete_codex_session.py --purge-deleted 1 --dry-run
```

Permanently purge one deleted conversation after explicit confirmation:

```bash
python3 scripts/delete_codex_session.py --purge-deleted 1 --yes
```

Preview permanent purge of an entire backup batch:

```bash
python3 scripts/delete_codex_session.py --purge-backup 1 --dry-run
```

Permanently purge an entire backup batch after explicit confirmation:

```bash
python3 scripts/delete_codex_session.py --purge-backup 1 --yes
```

## Safety Model

- Current conversation indexes are temporary and belong only to the latest displayed current-conversation table.
- Deleted conversation indexes are temporary and belong only to the latest displayed deleted-conversation table.
- `--dry-run` shows planned destructive changes without changing files.
- Deletion creates a timestamped backup with a `manifest.json`.
- Restore commands can run directly when the user has clearly selected what to restore.
- Permanent purge commands should only run after an explicit user confirmation.
- JSONL rewrites use temporary files and atomic replace.
- A lock file prevents concurrent destructive operations.

## Development

Validate script syntax:

```bash
python3 -m py_compile scripts/delete_codex_session.py
```

Check the CLI:

```bash
python3 scripts/delete_codex_session.py --help
```

Useful non-destructive checks:

```bash
python3 scripts/delete_codex_session.py --list
python3 scripts/delete_codex_session.py --list-backups
python3 scripts/delete_codex_session.py --list-deleted
python3 scripts/delete_codex_session.py --delete 1 --dry-run
python3 scripts/delete_codex_session.py --restore-deleted 1 --dry-run
python3 scripts/delete_codex_session.py --purge-deleted 1 --dry-run
python3 scripts/delete_codex_session.py --purge-backup 1 --dry-run
```

Validate the skill structure with the Codex skill creator validator when available:

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py .
```

## Project Layout

```text
codex-session-manager/
├── SKILL.md
├── README.md
├── LICENSE
├── agents/
│   └── openai.yaml
└── scripts/
    └── delete_codex_session.py
```

## License

MIT. See [LICENSE](LICENSE).
