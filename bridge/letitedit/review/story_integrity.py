"""Checks that a Short still contains the story selected before editing."""
from __future__ import annotations

import re

from letitedit.review.brief_check import (HEAR_SLACK_S, LINE_MATCH, ends_unheard, find_line, moment_description,
                                          said_at, speech_cues, unheard_at, words)

MISHEARD = 0.5      # a payoff the timeline's own words place where the review heard at least this share of it, in order


_DANGLING = {'a', 'an', 'the', 'and', 'but', 'or', 'because', 'if', 'when', 'while',
             'to', 'of', 'for', 'with', 'without', 'that', 'which', 'who', 'as',
             'at', 'in', 'on', 'from', 'by', 'than', 'so', 'very'}


def check(plan, cues, duration_s, kind, brief=None, said=None, deaf=None):
    """Return measured failures and missing evidence; never infer story quality from a length alone.

    The Short plan records a selected story length and a verbatim payoff line *before* the
    rough cut. Picture/sound payoffs go to editorial review, not transcript matching.
    said, deaf: the timeline's own words and brief_check.hearing()'s answer. A payoff the timeline's words place in a
    stretch the review's transcript heard nothing in, or talk whose end it didn't hear, is not checked, never missing.
    """
    if kind != 'short' or not isinstance(plan, dict):
        return {'findings': [], 'missing': []}
    short = (plan.get('deliverables') or {}).get('short') or {}
    findings, missing = [], []
    selected = short.get('selected_story_s')
    reason = short.get('length_reason')
    if selected is None or not str(reason or '').strip():
        missing.append('the Short plan needs selected_story_s and length_reason, chosen from the source before editing')
    else:
        try:
            selected = float(selected)
        except (TypeError, ValueError):
            missing.append('selected_story_s must be a number of seconds')
        else:
            if selected <= 0:
                missing.append('selected_story_s must be greater than zero')
            elif duration_s < selected * 0.75 and selected - duration_s >= 5:
                findings.append({'kind': 'story_length', 'severity': 'major', 'at_s': None,
                                 'what': f'Short is {duration_s:.1f} s; the selected story needs about {selected:.1f} s',
                                 'evidence': str(reason),
                                 'fix': 'restore the missing beat or revise the story selection with source evidence'})
            target = next((d.get('target_s') for d in (brief or {}).get('deliverables', [])
                           if isinstance(d, dict) and d.get('kind') == 'short' and d.get('target_s')), None)
            if target is not None and abs(float(target) - selected) >= max(5.0, 0.2 * selected):
                findings.append({'kind': 'target_recast', 'severity': 'major', 'at_s': None,
                                 'what': f'The Short target changed to {float(target):.1f} s after selecting a '
                                         f'{selected:.1f} s story',
                                 'evidence': str(reason),
                                 'fix': 'restore the selected target or revise the story plan with source evidence'})

    spoken = speech_cues(cues)
    payoff = short.get('payoff_line')
    moment = moment_description(short.get('payoff'))
    review = []
    if not isinstance(payoff, str) or not payoff.strip():
        if moment:
            review.append('picture/sound payoff: ' + moment + '; the reviewer must judge its action and release')
        else:
            missing.append('the Short plan needs payoff_line (exact spoken words) or payoff '
                           '(kind: visual/sound/audiovisual, description: the closing moment)')
    elif not spoken:
        missing.append('the export has no transcript to check its promised payoff')
    else:
        score, at, _, heard = find_line(payoff, spoken)
        gap = unheard_at(payoff, said, deaf) if score < LINE_MATCH else None
        place = said_at(payoff, said) if score < LINE_MATCH and not gap else None
        near = [c for c in spoken if place and c[0] - HEAR_SLACK_S < place[1] and c[1] + HEAR_SLACK_S > place[0]]
        there = find_line(payoff, near) if near else (0.0, None, None, '')
        if gap:
            missing.append(f"the promised payoff is at {gap[0]:.1f}-{gap[1]:.1f} s in the timeline's own words, where "
                           "the review's transcript heard nothing: listen to confirm it")
        elif score < LINE_MATCH and there[0] >= MISHEARD:
            # said there in the timeline's own words, and the review heard most of it there: a misheard word, not a cut
            findings.append({'kind': 'payoff_by_ear', 'severity': 'minor', 'at_s': round(place[0], 2),
                             'what': f'Payoff to confirm by ear: “{payoff}”',
                             'evidence': f"the timeline's own words have it at {place[0]:.1f}-{place[1]:.1f} s; the "
                                         f"review's transcript heard “{there[3]}” there ({there[0]:.0%})",
                             'fix': f'listen at {place[0]:.1f}-{place[1]:.1f} s: if it is hard to hear under the music '
                                    'or noise, lower them there'})
        elif score < LINE_MATCH:
            findings.append({'kind': 'missing_payoff', 'severity': 'major', 'at_s': None,
                             'what': f'Promised payoff is missing: “{payoff}”',
                             'evidence': f'closest heard line ({score:.0%}): “{heard}”',
                             'fix': 'put the payoff back, or listen and correct a transcript error'})

    if spoken and ends_unheard(said, deaf):
        missing.append("the review's transcript didn't hear the end of the talk: listen to whether it ends mid-thought")
    elif spoken:
        last = str(spoken[-1][2]).strip()
        tokens = words(last)
        if tokens and (tokens[-1].lower() in _DANGLING or re.search(r'[,;:\-–—]\s*$', last)):
            findings.append({'kind': 'mid_thought', 'severity': 'major', 'at_s': duration_s,
                             'what': 'The last spoken phrase sounds unfinished', 'evidence': last[-160:],
                             'fix': 'restore the end of this thought and listen to the last cut'})
    elif cues is None:
        missing.append('the export has no transcript to check whether speech ends mid-thought')
    result = {'findings': findings, 'missing': missing}
    if review:
        result['review'] = review
    return result
