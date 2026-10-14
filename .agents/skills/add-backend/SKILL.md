---
name: add-backend
description: Use when adding or changing a technique (backend) of a pipeline phase.
---

# Add or change a phase backend

1. Read `.agents/context/architecture.md` (registry, contracts) and the phase's `lib/<phase>/SPEC.md`.
2. Implement the technique as a pure function in `lib/<phase>/<name>.py` taking the phase's
   request from `core/contracts.py` and returning its result. No `Run`, paths, `meta.json`, progress.
3. Register it in `plugins/<phase>.py`:
   `@register("<phase>", "<name>", options=<PydanticOptions>, needs_gpu=..., description="...")`.
   Options: pydantic model with `extra="forbid"`, bounded numbers (the UI renders sliders from the schema).
4. Changing an existing backend's options incompatibly: bump `schema_version`, add a `migrate`
   step, add a test that an old options dict still loads.
5. GPU work runs under `core/gpu.gpu_lock` — set `needs_gpu=True`, the phase takes the lock.
6. Tests in `tests/test_plugins.py`: registered, options validate, swappable via settings,
   output contract respected. Existing goldens stay identical unless the task says otherwise.
7. UI needs no change (`BackendPicker` reads `GET /config/backends/<phase>`); run the UI build
   only if you touched `ui/`.
