# Western Comic — Reading format

## Reading direction: LEFT to RIGHT, TOP to BOTTOM

### Panel numbering

Top-left panel = 0. Read across each tier left→right, then down to next tier.

```
┌───────┬───────┬───────┐
│  P0   │  P1   │  P2   │  ← top tier
├───────┼───────┴───────┤
│  P3   │      P4       │  ← bottom tier (irregular widths are fine)
└───────┴───────────────┘
reading_order: [0, 1, 2, 3, 4]
```

### Western comic bubble conventions

- Speech: rounded bubble with a pointed tail
- Thought: cloud/oval with a chain of bubbles as tail (older convention) or rounded with wavy tail
- Caption box: rectangular, colored background, no tail — narrator or character caption
- SFX: bold onomatopoeia — POW, CRASH, BANG, THWIP — drawn into the art, no bubble
- Electronic/radio voice: rigid square/rectangular bubble with jagged or double border

### Captions vs narration

Caption boxes at the top of a panel often establish time/place ("Later that day...") — these are narrative captions, speaker_id = null.
Caption boxes in first person ("I knew this was a trap") may be attributed to the POV character.

### Gutter space

Space between panels is not a panel. Wide gutters between rows indicate time passage — note this in narrative_beat if relevant.
