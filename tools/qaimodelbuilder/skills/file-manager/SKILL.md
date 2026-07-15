---
name: File Manager
description: Read, write, organize and manage files and directories on the local filesystem.
tags: file, filesystem, organize
use_for: Reading files, writing files, listing directories, organizing project structure
---

# File Manager Skill

Manage local files and directories using `read`, `write`, `edit`, and `exec` tools.

## When to Use

- Reading file contents
- Creating or modifying files
- Listing directory contents
- Organizing project files
- Searching within files

## Operations

| Operation | Tool | Example |
|-----------|------|---------|
| Read file | `read(path)` | `read("config.json")` |
| Write file | `write(path, content)` | `write("output.txt", "Hello")` |
| Edit file | `edit(path, edits)` | `edit("file.py", [{...}])` |
| List dir | `exec("ls -la path")` | `exec("ls -la ./src")` |
| Search | `exec("grep -r pattern dir")` | `exec("grep -r TODO ./src")` |

## Safety Rules

- Always read a file before editing it
- Confirm before deleting files
- Never write to system directories
