# Workspace Rules & Guidelines

## 1. Token & Context Optimization
- Keep responses concise and focused on the immediate task.
- Avoid unnecessary conversational filler or redundant code re-summaries.
- Edit only relevant lines rather than reproducing entire files.

## 2. Code Quality & Design Patterns
- Be minimal amnd readable, do not overengineer and minimise the number of lines, report the number of lines used.
- Apply clean design patterns (Mixins, Strategy pattern, Factories) for maintainability.
- Keep functions and methods modular and short; avoid oversized monolithic functions.
- Maintain documentation integrity: preserve unrelated existing comments and docstrings.
- Do not write automated tests unless explicitly requested.

## 3. Project Architecture (Guillermo & Argo)
- **Guillermo (`project/`)**: Storyboard, generation pipelines (Scene, Agent, Task), Celery tasks, and Unfold admin.
- **Argo (`argo_project/`, `argo/`)**: Trading strategies, Nautilus Trader integrations, and financial tracking models.
- Keep custom applications separated and modular.
- Always use `django-unfold` compliant components and Tailwind-compatible admin mixins for UI consistency.

## 4. Interaction & Tooling
- Do not execute destructive or shell commands without explicit user permission.
- Always provide clickable markdown links with `file://` scheme for modified files and symbols.
