# Manga (Japanese) — Reading format

## Reading direction: RIGHT to LEFT, TOP to BOTTOM

This is the most important rule. Manga pages are read like Hebrew or Arabic text — starting from the right side.

### Panel numbering example

For a typical 6-panel page:

```
┌───────┬───────┬───────┐
│  P2   │  P1   │  P0   │  ← top row: read right→left = P0 first
├───────┼───────┼───────┤
│  P5   │  P4   │  P3   │  ← bottom row: read right→left = P3 next
└───────┴───────┴───────┘
reading_order: [0, 1, 2, 3, 4, 5]
```

For an irregular layout, always ask: which panel is in the top-right? That's panel 0.

### Within a panel: bubble reading order

Bubbles inside a single panel are also read RIGHT to LEFT.
The rightmost bubble in a panel is read before the leftmost.
Top before bottom when on the same horizontal level.

### Common manga conventions

**Narration boxes**: Usually rectangular, no tail, placed at the top or bottom corners of a panel. Often have a different background color or texture. These are the narrator's voice or a character's thought caption — speaker_id = null, bubble_type = "narration".

**Thought bubbles**: Cloud-shaped or have a chain of small circles as the tail instead of a pointed tail. bubble_type = "thought".

**Screentones**: The dotted/halftone texture background is decoration — not text.

**Vertical text**: Japanese manga often has vertical text in bubbles. Read top-to-bottom within the bubble, right-to-left across bubbles.

**SFX placement**: Large kanji/katakana drawn into the art (not in a bubble). Common examples:

- ドン/ドォン (DON) — impact
- ザワザワ (ZAWAZAWA) — crowd noise/unease
- ギリギリ (GIRIGIRI) — grinding/tension
- パン (PAN) — gunshot or slap
  Transcribe exactly as written. bubble_type = "sfx", speaker_id = null.

### Multi-page splash

If the page is a double-page spread (two pages shown), treat it as one page and read right-to-left across the full spread.
