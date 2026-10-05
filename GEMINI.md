# Workspace Rules

## 1. Efficiency & Scope
- **Minimize token consumption**: Keep responses concise and focused.
- **Do not write tests**: Never generate or edit test files unless explicitly requested.
- **No CLI or Multi-Agent Framework**: Do not run shell/terminal commands or spawn subagents.
- **Clickable Links**: Format all file and symbol links using the `file://` scheme (e.g., [file](file:///path/to/file#Lline) or [symbol](file:///path/to/file#Lline)) or workspace-relative paths.

## 2. Architecture & Design
- **Use design patterns**: Keep code modular with clean separation of concerns.
- **No long functions**: Keep every function short, focused, and under single-responsibility principles.

## 3. Library & Signature Constraints
- **NEVER patch external libraries**: Do not edit files inside `venv/`, `site-packages/`, or external dependencies. All bug fixes, monkeypatches, and adaptations must live strictly within the application codebase.
- **No unrequested flexible arguments**: Do not add flexible arguments, fallback keyword arguments (`**kwargs`), or optional permutations to function signatures unless explicitly requested. Keep signatures strict, minimal, and aligned to exact requirements.
