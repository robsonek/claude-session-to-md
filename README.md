# claude-session-to-md

Export [Claude Code](https://docs.anthropic.com/en/docs/claude-code) session transcripts from JSONL to clean, readable Markdown files.

Claude Code automatically saves full conversation transcripts as `.jsonl` files in `~/.claude/projects/`. This tool converts them into well-formatted Markdown with Obsidian-compatible callouts for easy browsing and archiving.

## Features

- **Convert sessions to Markdown** — extracts user and assistant messages, skips tool calls and thinking blocks
- **Detect active sessions** — finds currently running Claude Code processes and maps them to session files (macOS & Linux)
- **Browse all projects** — scans `~/.claude/projects/` to list every project with session counts, sizes, and last modified dates
- **Obsidian callouts** — output uses `[!question]` and `[!example]` callouts for clear visual distinction between user and Claude messages
- **Organized output** — files are saved in `sessions/<project-name>/<session-id>.md`
- **No dependencies** — pure Python 3, standard library only

## Installation

```bash
git clone https://github.com/robsonek/claude-session-to-md.git
cd claude-session-to-md
```

No `pip install` needed — just Python 3.6+.

## Usage

```bash
# Export the most recent session from the current project
python3 claude-session-to-md.py

# List all sessions in the current project (marks active ones)
python3 claude-session-to-md.py --list

# Export all sessions from the current project
python3 claude-session-to-md.py --all

# Detect active Claude Code sessions and export
python3 claude-session-to-md.py --active

# Browse all projects across ~/.claude/projects/ and pick one to export
python3 claude-session-to-md.py --projects

# Export a specific JSONL file
python3 claude-session-to-md.py /path/to/session.jsonl

# Export with a specific output path
python3 claude-session-to-md.py /path/to/session.jsonl output.md

# Override the output directory
python3 claude-session-to-md.py --all --output-dir ./my-export
```

## Commands

| Command | Description |
|---------|-------------|
| *(no args)* | Export the most recent session from the current project |
| `--list` | List all sessions with dates, sizes, and active status |
| `--all` | Export all sessions from the current project |
| `--active` | Detect running Claude Code processes, show their sessions, and export |
| `--projects` | Scan all projects in `~/.claude/projects/`, pick one (or all) to export |
| `--output-dir <path>` | Set custom output directory (works with `--all`, `--active`, `--projects`) |
| `-h`, `--help` | Show usage help |

## Output Structure

Files are organized by project name (mirroring Claude's internal directory naming):

```
sessions/
├── -Users-robson-AI-my-project/
│   ├── a1b2c3d4-...-session1.md
│   ├── e5f6g7h8-...-session2.md
│   └── ...
├── -Users-robson-AI-other-project/
│   └── ...
```

## Output Format

The generated Markdown uses [Obsidian callouts](https://help.obsidian.md/Editing+and+formatting/Callouts) for visual distinction:

```markdown
# Sesja Claude Code

**Data:** 2026-02-11 22:01
**ID sesji:** `d7fd6c4c-1452-4ac7-bd9b-6c3457617f99`

---

> [!question] User
> How do I implement authentication?

> [!example] Claude
> Here's how you can implement authentication...
```

- `[!question]` — blue block for user messages
- `[!example]` — purple block for Claude responses

The callouts render beautifully in Obsidian. In other Markdown viewers, they display as standard blockquotes which are still perfectly readable.

## Viewing in Obsidian

1. Open Obsidian
2. **Open folder as vault** → point to the `sessions/` directory
3. All exported conversations appear in the sidebar, organized by project

## How It Works

Claude Code stores session transcripts as JSONL files in `~/.claude/projects/<encoded-project-path>/`. Each line is a JSON object representing an event (user message, assistant response, tool use, tool result, thinking block, etc.).

This tool:
1. Reads the JSONL file line by line
2. Extracts only **user text messages** and **assistant text responses**
3. Deduplicates messages (the JSONL format can contain incremental updates)
4. Outputs clean Markdown with metadata (date, session ID)

### Active Session Detection

The `--active` flag detects running Claude Code sessions by:
- **macOS**: `ps aux` to find `claude` processes + `lsof` to get their working directories
- **Linux**: `ps aux` to find processes + `/proc/<pid>/cwd` symlink for working directories

It then maps the working directory to the corresponding project folder in `~/.claude/projects/` and identifies the session JSONL file.

## Platform Support

| Feature | macOS | Linux |
|---------|-------|-------|
| JSONL → Markdown conversion | Yes | Yes |
| `--list`, `--all`, `--projects` | Yes | Yes |
| `--active` (process detection) | Yes | Yes |

## License

MIT
