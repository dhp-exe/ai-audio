"""Shared package for the Audio AI production pipeline.

Modules:
    schema   - Pydantic contract for the AI Director output (EpisodeScript) and the voice registry.
    naming   - Deterministic file/stem naming helpers. Never hand-build stem names.
    config   - Environment-backed settings (API keys, defaults).

Skills under .claude/skills/*/scripts/ are thin CLIs that import from this package.
"""

__version__ = "0.1.0"
