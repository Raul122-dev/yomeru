"""
Backward-compatibility shim. The canonical location is: core.typesetting.stages.matching
"""
from .stages.matching import build_matcher, MatchResult, BaseMatcher  # noqa: F401
from .stages.matching.hungarian import HungarianMatcher  # noqa: F401

# legacy function alias
def match_dialogues_to_regions(image, dialogues, regions, hint_bboxes,
                                source_language="auto", ocr_weight=0.4,
                                spatial_weight=0.4, position_weight=0.2,
                                min_score=0.05):
    return build_matcher("hungarian").match(
        image=image, dialogues=dialogues, regions=regions,
        hint_bboxes=hint_bboxes, source_language=source_language,
        ocr_weight=ocr_weight, spatial_weight=spatial_weight,
        position_weight=position_weight, min_score=min_score,
    )