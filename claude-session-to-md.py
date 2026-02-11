#!/usr/bin/env python3
"""Convert Claude Code session transcripts (JSONL) to readable Markdown.

Usage:
  claude-session-to-md.py                    # convert the most recent session
  claude-session-to-md.py --active           # show active sessions and export selected
  claude-session-to-md.py --all              # export all sessions from current project
  claude-session-to-md.py --list             # list all sessions in current project
  claude-session-to-md.py --projects         # list all projects and export selected
  claude-session-to-md.py <file.jsonl>       # convert a specific file
  claude-session-to-md.py <file.jsonl> out.md  # convert with custom output path
  claude-session-to-md.py --output-dir ./export  # custom output dir (with --all/--active/--projects)
"""

import json
import subprocess
import sys
import os
import re
from datetime import datetime


CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_BASE_DIR = os.path.join(SCRIPT_DIR, "sessions")


def get_active_sessions():
    """Detect active Claude Code sessions by inspecting running processes."""
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return []

    active = []
    for line in result.stdout.splitlines():
        if "claude" not in line.lower():
            continue
        if "grep" in line or "claude-session-to-md" in line:
            continue

        parts = line.split()
        if len(parts) < 2:
            continue
        pid = parts[1]

        cwd = get_process_cwd(pid)
        if not cwd:
            continue

        # Find session ID from --resume flag or latest JSONL
        resume_id = None
        if "--resume" in line:
            idx = line.index("--resume")
            match = re.search(r"--resume\s+([a-f0-9-]+)", line[idx:])
            if match:
                resume_id = match.group(1)

        cwd_encoded = cwd.replace("/", "-")
        session_dir = os.path.join(CLAUDE_PROJECTS_DIR, cwd_encoded)

        session_file = None
        session_id = None

        if resume_id and os.path.isdir(session_dir):
            candidate = os.path.join(session_dir, f"{resume_id}.jsonl")
            if os.path.exists(candidate):
                session_file = candidate
                session_id = resume_id

        if not session_file and os.path.isdir(session_dir):
            # Most recently modified JSONL = likely the active session
            jsonl_files = [
                os.path.join(session_dir, f)
                for f in os.listdir(session_dir)
                if f.endswith(".jsonl")
            ]
            if jsonl_files:
                session_file = max(jsonl_files, key=os.path.getmtime)
                session_id = os.path.splitext(os.path.basename(session_file))[0]

        first_prompt = get_first_prompt(session_file) if session_file else None

        active.append({
            "pid": pid,
            "cwd": cwd,
            "session_id": session_id,
            "session_file": session_file,
            "first_prompt": first_prompt,
            "resumed": resume_id is not None,
        })

    return active


def get_process_cwd(pid):
    """Get the working directory of a process (macOS + Linux)."""
    import platform
    system = platform.system()

    if system == "Linux":
        # /proc/<pid>/cwd is a symlink to the working directory
        try:
            path = os.readlink(f"/proc/{pid}/cwd")
            if os.path.isdir(path) and ".claude" not in path:
                return path
        except (OSError, PermissionError):
            pass
        return None

    # macOS: use lsof
    try:
        result = subprocess.run(
            ["lsof", "-p", pid, "-Fn"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if line.startswith("n/"):
                path = line[1:]
                if os.path.isdir(path) and ".claude" not in path:
                    return path
    except Exception:
        pass
    return None


def get_first_prompt(jsonl_path):
    """Extract the first user prompt from a JSONL session file."""
    if not jsonl_path or not os.path.exists(jsonl_path):
        return None
    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("type") == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content")
                    if isinstance(content, str) and content.strip():
                        text = " ".join(content.split())
                        return text[:80] + "..." if len(text) > 80 else text
    except Exception:
        pass
    return None


def get_all_sessions():
    """Return all sessions from the current project directory."""
    cwd_encoded = os.getcwd().replace("/", "-")
    session_dir = os.path.join(CLAUDE_PROJECTS_DIR, cwd_encoded)

    if not os.path.isdir(session_dir):
        return [], session_dir

    sessions = []
    index_path = os.path.join(session_dir, "sessions-index.json")
    index_data = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, "r") as f:
                index_data = {
                    e["sessionId"]: e
                    for e in json.load(f).get("entries", [])
                }
        except Exception:
            pass

    jsonl_files = sorted(
        [
            os.path.join(session_dir, f)
            for f in os.listdir(session_dir)
            if f.endswith(".jsonl")
        ],
        key=os.path.getmtime,
        reverse=True,
    )

    active_sessions = {s["session_id"] for s in get_active_sessions() if s["session_id"]}

    for jsonl_file in jsonl_files:
        sid = os.path.splitext(os.path.basename(jsonl_file))[0]
        idx = index_data.get(sid, {})
        mtime = os.path.getmtime(jsonl_file)
        size = os.path.getsize(jsonl_file)

        sessions.append({
            "session_id": sid,
            "file": jsonl_file,
            "modified": datetime.fromtimestamp(mtime),
            "size": size,
            "first_prompt": idx.get("firstPrompt") or get_first_prompt(jsonl_file),
            "summary": idx.get("summary"),
            "message_count": idx.get("messageCount"),
            "is_active": sid in active_sessions,
        })

    return sessions, session_dir


def jsonl_to_markdown(jsonl_path, output_path=None):
    """Convert a JSONL session file to Markdown."""
    if not os.path.exists(jsonl_path):
        print(f"  File not found: {jsonl_path}")
        return False

    if output_path is None:
        output_path = os.path.splitext(jsonl_path)[0] + ".md"

    messages = []
    seen_user_texts = set()
    # Group assistant messages by message ID, keep only the longest (final) version
    assistant_msgs = {}  # msg_id -> {role, text, timestamp, order}
    order_counter = 0

    with open(jsonl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            message = entry.get("message", {})
            role = message.get("role")
            content = message.get("content")
            timestamp = entry.get("timestamp", "")
            msg_id = message.get("id", "")

            if entry_type == "user" and role == "user" and isinstance(content, str):
                if content not in seen_user_texts:
                    seen_user_texts.add(content)
                    messages.append({
                        "role": "user",
                        "text": content,
                        "timestamp": timestamp,
                        "order": order_counter,
                    })
                    order_counter += 1

            if entry_type == "assistant" and role == "assistant" and isinstance(content, list):
                # Collect all text blocks from this entry
                full_text = "\n".join(
                    block.get("text", "").strip()
                    for block in content
                    if block.get("type") == "text" and block.get("text", "").strip()
                )
                if not full_text:
                    continue

                if msg_id and msg_id in assistant_msgs:
                    # Keep the longer version (later streaming update)
                    if len(full_text) >= len(assistant_msgs[msg_id]["text"]):
                        assistant_msgs[msg_id]["text"] = full_text
                        assistant_msgs[msg_id]["timestamp"] = timestamp
                else:
                    key = msg_id or f"_no_id_{order_counter}"
                    assistant_msgs[key] = {
                        "role": "assistant",
                        "text": full_text,
                        "timestamp": timestamp,
                        "order": order_counter,
                    }
                    order_counter += 1

    # Merge user messages and deduplicated assistant messages, sort by order
    messages.extend(assistant_msgs.values())
    messages.sort(key=lambda m: m["order"])

    if not messages:
        print(f"  No messages in: {os.path.basename(jsonl_path)}")
        return False

    lines = []
    session_id = os.path.splitext(os.path.basename(jsonl_path))[0]
    lines.append("# Claude Code Session")
    lines.append("")
    if messages[0].get("timestamp"):
        ts = messages[0]["timestamp"]
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            lines.append(f"**Date:** {dt.strftime('%Y-%m-%d %H:%M')}")
        except Exception:
            lines.append(f"**Date:** {ts}")
    lines.append(f"**Session ID:** `{session_id}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Merge consecutive messages from the same role
    merged = []
    for msg in messages:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["text"] += "\n\n" + msg["text"]
        else:
            merged.append(dict(msg))

    for msg in merged:
        # Strip HTML tags that break Obsidian callouts
        text = re.sub(r"</?summary>", "", msg["text"]).strip()
        if not text:
            continue
        text_lines = text.splitlines()
        if msg["role"] == "user":
            lines.append("> [!question] User")
        else:
            lines.append("> [!example] Claude")
        for tl in text_lines:
            lines.append(f"> {tl}")
        lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    print(f"  Saved: {output_path} ({len(messages)} messages)")
    return True


def format_size(size_bytes):
    """Format file size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def cmd_list():
    """List all sessions in the current project."""
    sessions, session_dir = get_all_sessions()
    if not sessions:
        print(f"No sessions in: {session_dir}")
        return

    print(f"Sessions in: {session_dir}\n")
    for i, s in enumerate(sessions, 1):
        status = " ACTIVE" if s["is_active"] else ""
        prompt = s["first_prompt"] or "(no prompt)"
        date = s["modified"].strftime("%Y-%m-%d %H:%M")
        size = format_size(s["size"])
        msgs = f", {s['message_count']} msg" if s["message_count"] else ""
        print(f"  [{i}]{status} {date}  {size}{msgs}")
        print(f"      {prompt}")
        if s["summary"]:
            print(f"      -> {s['summary']}")
        print()


def cmd_active(output_dir=None):
    """Show active sessions and export."""
    active = get_active_sessions()
    if not active:
        print("No active Claude Code sessions.")
        return

    print(f"Active Claude Code sessions ({len(active)}):\n")
    exportable = []
    for i, s in enumerate(active, 1):
        prompt = s["first_prompt"] or "(no prompt)"
        resumed = " (resumed)" if s["resumed"] else ""
        print(f"  [{i}] PID {s['pid']}{resumed}")
        print(f"      Directory: {s['cwd']}")
        print(f"      Prompt:    {prompt}")
        if s["session_file"]:
            print(f"      File:      {os.path.basename(s['session_file'])}")
            exportable.append(s)
        print()

    if not exportable:
        print("No files to export.")
        return

    if len(exportable) == 1:
        choice = 0
    else:
        try:
            raw = input(f"Export which? [1-{len(exportable)}, a=all, Enter=cancel]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not raw:
            return
        if raw.lower() == "a":
            for s in exportable:
                out = get_output_path(s["session_file"], output_dir)
                jsonl_to_markdown(s["session_file"], out)
            return
        try:
            choice = int(raw) - 1
            if choice < 0 or choice >= len(exportable):
                print("Invalid number.")
                return
        except ValueError:
            print("Invalid choice.")
            return

    s = exportable[choice]
    out = get_output_path(s["session_file"], output_dir)
    jsonl_to_markdown(s["session_file"], out)


def cmd_all(output_dir=None):
    """Export all sessions from the current project."""
    sessions, session_dir = get_all_sessions()
    if not sessions:
        print(f"No sessions in: {session_dir}")
        return

    print(f"Exporting {len(sessions)} sessions...\n")
    exported = 0
    for s in sessions:
        out = get_output_path(s["file"], output_dir)
        if jsonl_to_markdown(s["file"], out):
            exported += 1

    print(f"\nDone. Exported {exported}/{len(sessions)} sessions.")


def get_project_name(jsonl_path):
    """Extract the project name from a JSONL file path."""
    parent = os.path.dirname(os.path.abspath(jsonl_path))
    dirname = os.path.basename(parent)
    # If inside a subagent folder, go up
    if dirname == "subagents":
        parent = os.path.dirname(os.path.dirname(parent))
        dirname = os.path.basename(parent)
    return dirname


def get_all_projects():
    """Scan ~/.claude/projects/ and return a list of projects with metadata."""
    if not os.path.isdir(CLAUDE_PROJECTS_DIR):
        return []

    projects = []
    for name in sorted(os.listdir(CLAUDE_PROJECTS_DIR)):
        project_dir = os.path.join(CLAUDE_PROJECTS_DIR, name)
        if not os.path.isdir(project_dir):
            continue

        jsonl_files = [
            os.path.join(project_dir, f)
            for f in os.listdir(project_dir)
            if f.endswith(".jsonl")
        ]
        if not jsonl_files:
            continue

        total_size = sum(os.path.getsize(f) for f in jsonl_files)
        latest = max(jsonl_files, key=os.path.getmtime)
        latest_mtime = datetime.fromtimestamp(os.path.getmtime(latest))

        # Read original path from sessions-index.json, fallback: decode from folder name
        original_path = None
        index_path = os.path.join(project_dir, "sessions-index.json")
        if os.path.exists(index_path):
            try:
                with open(index_path, "r") as f:
                    original_path = json.load(f).get("originalPath")
            except Exception:
                pass
        if not original_path:
            original_path = "/" + name.lstrip("-").replace("-", "/")

        projects.append({
            "name": name,
            "dir": project_dir,
            "session_count": len(jsonl_files),
            "total_size": total_size,
            "latest_modified": latest_mtime,
            "original_path": original_path,
        })

    return projects


def cmd_projects(output_dir=None):
    """List all projects and export selected one."""
    projects = get_all_projects()
    if not projects:
        print(f"No projects in: {CLAUDE_PROJECTS_DIR}")
        return

    print(f"Claude Code projects ({len(projects)}):\n")
    for i, p in enumerate(projects, 1):
        size = format_size(p["total_size"])
        date = p["latest_modified"].strftime("%Y-%m-%d %H:%M")
        path = p["original_path"] or "(unknown path)"
        print(f"  [{i}] {p['name']}")
        print(f"      Path:     {path}")
        print(f"      Sessions: {p['session_count']}  Size: {size}  Latest: {date}")
        print()

    try:
        raw = input(f"Export which? [1-{len(projects)}, a=all, Enter=cancel]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not raw:
        return

    if raw.lower() == "a":
        selected = projects
    else:
        try:
            choice = int(raw) - 1
            if choice < 0 or choice >= len(projects):
                print("Invalid number.")
                return
            selected = [projects[choice]]
        except ValueError:
            print("Invalid choice.")
            return

    for p in selected:
        print(f"\n--- {p['name']} ({p['session_count']} sessions) ---\n")
        jsonl_files = sorted(
            [
                os.path.join(p["dir"], f)
                for f in os.listdir(p["dir"])
                if f.endswith(".jsonl")
            ],
            key=os.path.getmtime,
            reverse=True,
        )
        exported = 0
        for jf in jsonl_files:
            out = get_output_path(jf, output_dir)
            if jsonl_to_markdown(jf, out):
                exported += 1
        print(f"  Exported {exported}/{len(jsonl_files)} sessions.")

    print("\nDone.")


def get_output_path(jsonl_path, output_dir=None):
    """Calculate output path: <base>/<project_name>/<session_id>.md"""
    session_id = os.path.splitext(os.path.basename(jsonl_path))[0]
    project_name = get_project_name(jsonl_path)
    base = output_dir or SESSIONS_BASE_DIR
    project_folder = os.path.join(base, project_name)
    os.makedirs(project_folder, exist_ok=True)
    return os.path.join(project_folder, f"{session_id}.md")


def main():
    args = sys.argv[1:]

    output_dir = None
    if "--output-dir" in args:
        idx = args.index("--output-dir")
        if idx + 1 < len(args):
            output_dir = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            print("Missing path after --output-dir")
            sys.exit(1)

    if not args:
        # Default: export the most recent session
        cwd_encoded = os.getcwd().replace("/", "-")
        session_dir = os.path.join(CLAUDE_PROJECTS_DIR, cwd_encoded)

        if not os.path.isdir(session_dir):
            print(f"Session directory not found: {session_dir}")
            print(__doc__)
            sys.exit(1)

        jsonl_files = [
            os.path.join(session_dir, f)
            for f in os.listdir(session_dir)
            if f.endswith(".jsonl")
        ]
        if not jsonl_files:
            print("No session files found.")
            sys.exit(1)

        jsonl_path = max(jsonl_files, key=os.path.getmtime)
        print(f"Latest session: {os.path.basename(jsonl_path)}")
        out = get_output_path(jsonl_path, output_dir)
        jsonl_to_markdown(jsonl_path, out)

    elif args[0] == "--active":
        cmd_active(output_dir)

    elif args[0] == "--all":
        cmd_all(output_dir)

    elif args[0] == "--projects":
        cmd_projects(output_dir)

    elif args[0] == "--list":
        cmd_list()

    elif args[0] == "--help" or args[0] == "-h":
        print(__doc__)

    elif args[0].startswith("-"):
        print(f"Unknown option: {args[0]}")
        print(__doc__)
        sys.exit(1)

    else:
        jsonl_path = args[0]
        out = args[1] if len(args) > 1 else get_output_path(jsonl_path, output_dir)
        jsonl_to_markdown(jsonl_path, out)


if __name__ == "__main__":
    main()
