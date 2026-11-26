# Learning a reference's lighting (letitedit-lighting, during Learn)

Read in full during Learn, before `letitedit_learn(action="lighting_reference")` and the save of a Look with lighting.

After the importer and the visual-role review, call `letitedit_learn(action="lighting_reference",
reference=<report.json>, out=<new private folder>, package={samples_per_scene:3,max_scenes:100})`.
Use its enriched `report.json` in subsequent prepare/save calls, retaining visual and sound enrichments.
Reviewed role boundaries split the importer shots; no face does not mean b-roll. Unreviewed roles stay unknown.
Read every returned limitation and omitted-scene count. Sparse samples can miss moving light, flashes and grading
changes inside a shot; add denser samples or split the report intervals when frame inspection shows one.
Inspect the saved frames and the window images yourself (the oval around the face and the oval the room starts beyond;
white inside the first, black outside the second). Exclude captions with the report text-event boxes; boxes
are detector estimates, so missing text can still contaminate measurements. Clothing, hair and a bright wall are not
told apart from the window and the room. Missing face or skin is unknown.
The profile's `live.reference_stops` is the median face-to-room separation of the talking-head samples that show a face
and no native effect; the recipe states it, and the lighting op reads it back.

Compare subject and background separately: display-luma median, p05 blacks, p90-p10 contrast, saturation,
mean RGB and the bright-pixel RGB proxy. Use skin/face values for the visible key-colour appearance, and
left/right background values for visible side-colour appearance; neither identifies the lamp or its CCT.
The corner/centre ratio can come from composition rather than a vignette. Haze and bloom cannot be reliably
separated from set, lens and grade here: record a visual observation or unknown, never invent effect strengths.
Review different b-roll scenes independently instead of averaging their grades into the talking head.

Save with the ordinary Look conflict guard. `lighting` accepts one measured profile or a list. If omitted,
enriched reports supply it, otherwise the previous revision is kept; null explicitly removes it.
The immutable sibling `lighting.json` and Measured lighting recipe section are the reuse contract.
For a lighting-only revision, supply `lighting_only:true` with the current recipe, metadata, observations,
limitations and Theme unchanged. The save retains the earlier non-lighting evidence even if importer rules
have changed since that revision; unrelated changes are refused. Re-read after a revision conflict.
