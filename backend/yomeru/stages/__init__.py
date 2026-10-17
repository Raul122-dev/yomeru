"""Pipeline stages, one package each: detection → analysis (read & translate) → matching →
inpainting → rendering. Every stage holds its orchestration (`phase.py`), its registered
techniques (`plugins.py`) and their implementation."""
