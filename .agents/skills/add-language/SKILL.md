---
name: add-language
description: Use when adding a language or a language-specific tuning.
---

# Add a language or a language-specific rule

All language behaviour lives in `src/yomeru/core/languages.py`:
`GENERAL` → `SCRIPTS[script]` → `LANGUAGES[name]`, each layer overriding only what differs.

New language:
1. Add `"<Name as in settings>": ("<script>", {overrides})` to `LANGUAGES`
   (hyphenation = a pyphen dictionary code or None; OCR codes for EasyOCR; reading direction).
2. Add it to `ui/src/lib/languages.ts` if it must be selectable.
3. Test in `tests/test_languages.py` (resolved fields).

New tuning (e.g. opening marks ¡¿, French space before ! ?):
1. Add a field to `LanguageProfile` with the general default; override per script/language.
2. Read it where the decision is made — `profile(setting)` for run-level source/target rules,
   `text_rules(text)` for rules that depend on the script a text is written in.
3. Test the field AND the behaviour; existing goldens stay identical for languages you didn't touch.
Never add `if language in (...)` or `is_cjk_text` decisions outside `core/languages.py`.
