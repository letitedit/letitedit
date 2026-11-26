"""Adapted from rea-video classify.py, commit 3522250b4d3e667610a175c0f188ac3d725b41cd.

Modified: taxonomy only; unknown added, no forensic classifier or model downloads.
Apache-2.0; upstream attribution and terms are in sibling NOTICE and LICENSE.
"""

LABELS = ("live_action", "ai_video", "avatar", "cg_3d", "code_render",
          "screen_capture", "still_motion", "static_hold", "anim_2d",
          "stop_motion", "film_footage", "unknown")
GROUPS = {"ai_video": "generated", "avatar": "generated",
          "cg_3d": "three_d", "code_render": "code", "anim_2d": "animation",
          "stop_motion": "live_action", "film_footage": "live_action"}


def group_of(label):
    return GROUPS.get(label, label)
