# Auto-detect — Reading format

Determine the reading direction by examining the page carefully before extracting anything.

## Detection methodology

### Step 1: Check text orientation

- **Vertical text** (characters stacked top-to-bottom) → likely manga/RTL
- **Horizontal text** → could be LTR or RTL depending on language

### Step 2: Check script

- **Japanese** (hiragana/katakana/kanji mix) → manga RTL
- **Korean** (hangul) → manhwa LTR, likely vertical scroll
- **Chinese** (kanji only, no kana) → manhua, check traditional vs simplified for direction
- **Latin/Western** → comic LTR

### Step 3: Check panel flow

- Look for dialogue that continues across panels — the "setup" panel comes before the "response" panel
- Character gaze: characters typically look TOWARD the next panel they interact with
- Action-reaction: the action panel precedes the reaction panel

### Step 4: Apply the right format rules

Once detected, apply the rules from the appropriate format:

- Manga RTL → panel 0 is top-right
- Manhwa/Manhua/Comic LTR → panel 0 is top-left

### When truly ambiguous

Default to LTR if you cannot determine the direction from the above signals.
