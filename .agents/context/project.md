# Project — yomeru

AI-assisted translation and typesetting of manga, manhwa, manhua and western comics.
Upload raw pages → get translated pages, with an editor for every step.
Repo: https://github.com/rauldev-yoru/yomeru · Owner: Raul 夜 (rauldev-yoru).

## Goal: v1.0
Anyone can clone the repo and run it locally (`uv sync`, `bash start.sh`), with
their own model provider. Roadmap phases: 0–2 done (bugs, structure, UI, plugins),
3 render/inpainting quality (closing), 4 UX v1.0, 5 release (docs, CI, 1.0.0).

## Product decisions (do not change without Raul)
- **Self-contained.** No dependency on other services of the owner's machine.
  External pieces are only model APIs and optional local model servers (Ollama) it detects.
- **API is the default** for reading/translating (`vlm` technique). A run refuses
  to start without a configured provider + vision model; the only alternative is the
  **local** technique (Ollama), always labelled *Experimental*. Never make local the
  default or an automatic fallback.
- **Separate reading/translation** is an optional switch (off by default). When on,
  translation is context-aware (story, characters, situation) — never literal,
  especially Asian → Spanish.
- **Detection is the pipeline's index.** ogkalu RT-DETR is the only detector
  (labels `bubble`, `text_bubble`, `text_free`); matching, inpainting and rendering
  are keyed on its region ids. CTD was removed — don't bring it back.
- **Every phase is a plugin** behind a fixed input/output contract: the technique can
  change (e.g. render with an image model), the data chain can't.
- **Language-specific rules** live only in `config/languages.py` profiles (code-only).
- **Bind 127.0.0.1, no auth; API keys never leave the server** (masked in the API).
- **Model weights are never in the repo** (downloaded on first use into `data/models/`).
- **UI:** React + Vite + shadcn/ui + Tailwind, dark mode. No new screens that depend
  on design decisions without asking.
- **Quality is judged by how the page reads**, against the base version and a human
  scanlation — not by metrics alone.

## Data that is NOT in the repo
`data/` (git-ignored): runs, `config.json` (keys), model weights, `goldens/`
(frozen reference runs for regression checks), and the owner's test corpus.
Agents without `data/goldens` skip the golden checks and say so.
