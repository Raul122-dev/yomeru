# Matching

Decide which detected region each dialogue of the reading goes into.

## Contract
- Phase: `stages/matching/phase.py` → backend `cascade` (`stages/matching/plugins.py`) →
  `stages/matching/cascade.match_page`, a pure function of
  `pipeline/contracts.MatchRequest` (page image, active detections, dialogues with
  user edits merged, source language, comic format) returning a `PageMatch`
  (`{dialogue_index: MatchResult}`, orphaned regions, rescued count, regions
  located by OCR). The phase writes the render log the editors read
  (`s3_matching`); the matching editor saves `pNN_matches_refined.json`.

## Cascade
1. **direct** — the model's `region_id` (a `bubble` resolves to the text region
   inside it); each region is claimed once.
2. **hungarian** — unresolved dialogues vs unclaimed text regions, score =
   spatial overlap with the dialogue bbox × `spatial_weight` + OCR trigram
   similarity × `ocr_weight` (`hungarian.py`, scipy `linear_sum_assignment`).
3. **reading order** — still unresolved: the next free region in manga reading
   order (`reading_order._sort_reading_order`), only near the dialogue's bbox.
4. **orphans** — text regions no dialogue landed in.
5. **rescue** — OCR of the orphans (`ocr.py`: manga-ocr for Japanese, EasyOCR
   otherwise): merged into a dialogue or matched to an unmatched one by text.
Repeated sound effects read as one line are split per occurrence
(`split_repeated_sfx`, saved as a page edit and flagged for review).
