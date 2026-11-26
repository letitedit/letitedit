---
name: letitedit-review
description: Brief for a separate critic that reviews a letitedit render end to end - evidence-backed problems with timecodes and severity (critical / major / minor), story, pacing, shots, sound, text and the brief. Writes review.json. Runs inside letitedit_review_bundle (critic='run'), on whichever AI the person has.
metadata:
  version: 0.3.0
---

# Critic review

Agents' own checks are almost all technical (5.5% of their notes concern story, pacing or shot choice, against 66%
of human editors' notes) and they claim success in 93% of runs [RES, Timeline-Bench]. A separate critic fixes the
first; the gate fixes the second.

A brief's `song_added_when_posting` means the file has no song on purpose: the person adds it in the phone app. Never report the
missing music; judge the sound the viewer will have with a song on top, and treat cuts on its beats as deliberate.

A brief's `preferences` are wishes below its requirements, which the editor reports on itself: a preference that wasn't
followed is not a problem. One listed anyway takes kind `preference`, and the review leaves it out of its counts.

Past the round limit a reviewer may be asked one narrow question, `--targeted`: only the open items, with the pictures and words
around each; fixed or still open for each, nothing new.

Run it through the gate: `letitedit_review_bundle(video, project, brief, critic='run')` gives the bundle to a separate
run of an AI on this PC: a different AI from the editor when one is available, else the same AI as a fresh session.
Someone with one AI gets a full review. On its own: `letitedit_critic(video, kind, brief, out)`. The critic never sees
the editor's reasoning, only:
- the brief, the story plan's logline or purpose and its sections when there is one, and the questions of the
  brief's kind of video (letitedit-modes: section 8 of each mode file, e.g. tutorial: can each step be copied at
  normal speed);
- the WHOLE video: contact pages in time order (one frame every 1 s up to 3 min, 2 s up to 15 min, 4 s beyond) and a
  page of larger frames at key and flagged moments (the old single sheet stopped at 4:48);
- the complete transcript of the render, and the measurements.

Instructions to the critic:
- Judge only what you can point to: every problem has a time, the evidence (what is seen or heard) and a fix.
- Severity: critical = should not be published as it is (a broken promise, a required moment missing, wrong or
  unreadable key text, a glaring technical fault); major = a viewer would notice it and it hurts the video; minor = polish,
  or something a viewer would not notice.
- Owner: `person` only for what only they have (a real recording, proof of a number, the real link, a fact to verify, their
  decision); `ai` for anything the edit can change. The bundle checks this: a cut through a word is never the person's.
- After the first round the critic gets a short list of what earlier rounds found. It says in `previously` whether each open item is
  really fixed, doesn't raise the person's items again, and adds something new only if it clears the bar for its severity.
- The transcript comes from a small speech model: a word that reads oddly is probably misheard, at most a minor to confirm by ear.
- A caption caught mid-fade on one tile isn't dim.
- Consider story (could you retell what it is about and what it leaves you with; for a goal story: goal, obstacle
  and change; does the ending pay the hook; does a long talk end on a closing beat, not stop mid-conversation; is
  there one ending: a second closing movement after the video has already ended, such as a wrap-up that starts again
  on new subjects after the last event lands, is a major), pacing judged against the brief's feel, reference and kind of video
  (not against a fixed idea that Shorts must be fast or documentaries slow), shot choice, sound, on-screen text and
  captions, the mode's questions, and every requirement in the brief. Finding none is a valid answer; do not
  invent problems to reach a number.
- Look at the frame itself: the picture shrunk inside a blurred or empty border when the footage could fill the
  frame reads as a broken video (major). So does a drawn scene that sits still like a slide. So does a scene that doesn't answer the words: take
  three key words from the transcript and look at the tiles there. Could a stranger with the sound off say what is being talked about
  from what's drawn? A pretty backdrop that barely changes, or one object changing shape, is a major even when it's beautiful. A drawn chart
  or screen that moves on the words is not a fault. Say what is on screen, not only what is missing from the story.
- Say which pages and time ranges you looked at.
- Check key text and logos against the frame and their own boxes, including the outgoing-frame pages. A logo
  cut away before its name has fully revealed is incomplete even without geometric cropping. Compare earlier
  frames with the outgoing frame; quote the visible letters and time. Unreadable or incomplete key branding is
  major, not merely a style mismatch. Do not infer clipping from an intermediate reveal that finishes before the cut.

`review.json`: `{"verdict": "block|revise|ok-with-notes|ok", "retell": "...", "promise_paid": true/false,
"checked": "...", "problems": [{"rank", "t", "severity", "kind": "story|pacing|shots|sound|text|technical|brief", "owner": "ai|person",
"evidence", "fix"}], "previously": [{"id", "status": "fixed|still_open"}], "modes": [...], "mode_questions": [...]}`

The editor answers every problem: fixed, or not fixed with a reason. A critical problem blocks delivery.
