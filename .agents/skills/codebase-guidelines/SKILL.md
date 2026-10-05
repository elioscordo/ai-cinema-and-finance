---
name: codebase-guidelines
description: Enforces core codebase constraints including prohibiting patching external libraries and avoiding unrequested flexible arguments.
---

# Codebase Guidelines & Development Constraints

Use these instructions whenever implementing, refactoring, or designing code in this workspace:

## 1. Never Patch External Libraries
- Under no circumstances should files inside `venv/`, `site-packages/`, or external library paths be modified.
- All bug fixes, data sanitization, lifecycle hooks, and workarounds must reside exclusively within project code (e.g. `argo/`).

## 2. Strict Signatures (No Unrequested Flexible Arguments)
- Do not introduce flexible, permissive, or fallback arguments (such as `*args`, `**kwargs`, or optional argument aliases) unless explicitly instructed.
- Keep signatures minimal, exact, and strictly bound to the explicit requirements.

## 3. General Development Rules
- Minimize token consumption.
- Do not write or generate tests.
- Use established design patterns and maintain short functions.
- Do not execute CLI/terminal commands or invoke subagents.
- Format all clickable file and symbol links using the `file://` scheme.
