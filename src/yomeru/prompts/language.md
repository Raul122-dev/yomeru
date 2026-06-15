# Language instructions

{{#if SOURCE_LANGUAGE_KNOWN}}

## Source language: {{SOURCE_LANGUAGE}}

Extract all dialogue text VERBATIM in {{SOURCE_LANGUAGE}}.

- Do not normalize spelling, punctuation, or formatting
- Preserve hyphenation (e.g. "EX-OR-CISTS" stays as written)
- Preserve ellipses, dashes, and emphasis marks
  {{else}}

## Source language: auto-detect

Extract text verbatim in whatever language appears in the image.
{{/if}}

{{#if TRANSLATE}}

## Translation: {{SOURCE_LANGUAGE}} → {{TARGET_LANGUAGE}}

For every dialogue entry, add `text_translated` with an accurate {{TARGET_LANGUAGE}} translation.

Translation guidelines:

- Preserve the speaker's register (formal/informal/dialect)
- Maintain tone markers (shouting stays emphatic, whispering stays soft)
- Adapt honorifics: keep them if meaningful (e.g. "-sama", "-ssi"), or translate the relationship they imply
- SFX: adapt phonetically to target language rather than translating literally
  - Japanese ドン → "BOOM" or "THUD" depending on context
  - Korean 쾅 → "BANG" or "CRASH"
- Sentence fragments and interrupted speech should remain fragmented
- Do not add meaning that isn't in the source

{{else}}

## No translation

Do NOT include `text_translated` in any dialogue entry.
{{/if}}

{{#if UI_LANGUAGE}}

## Descriptions language: {{UI_LANGUAGE}}

Write ALL of the following fields in {{UI_LANGUAGE}}:

- `scene.location`, `scene.mood`, `scene.narrative_beat`
- `page_summary`
- `characters_seen[].description`, `.emotional_state`, `.last_action`

The `text` field (and `text_translated` if present) follow their own language rules above — this only applies to your analytical descriptions.
{{/if}}
