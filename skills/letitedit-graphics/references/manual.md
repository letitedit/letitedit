# letitedit-graphics: reasons, evidence and tool details behind the checklist

Read the part you need. Every rule is in SKILL.md; this file holds why some of them hold, what was measured, and the
details of the tools they name.

## The evidence tags
The library gives principles (purpose, restraint, honesty) and no graphics craft, so how-to defaults are [GEN]; our
explanatory text should clarify the story, not merely decorate it [OURS]. letitedit-craft owns jump-off points,
showing time pass and the repetition ledger; letitedit-captions places and spells words; letitedit-shorts owns the
first frame. Calls: references/devices.md.

## 3. Making each device
- **Pointer:** `letitedit_annotate(project, clip, kind, target, at, follow='track', text=...)` takes a box in the
  clip's own upright source picture, maps it through crops and zooms, tracks the object, hides the pointer where
  tracking is lost, and keeps the label clear of captions, faces and the apps' zones (`platform=`).
- **Real pictures:** `search` (set `kind`: logo, person, place, book...) gives numbered candidates with their licence,
  then `fetch` saves the chosen one beside the project. A made-up version of a well-known logo, cover or face reads as
  wrong at a glance; the real one is recognised in a few frames, so a pop-up, a book cover in a list or a place in a
  story starts from the real picture [OURS; GEN].

## 4. Titles, names and chapters
Graphics designed for the video beat filled-in templates in every comparison we ran; a run with five graphic styles
lost.

## Scenes made with code
- A speaker's words turning into a world drawn just for them is what people come to letitedit for.
- For a talking head, `letitedit_code_scene(create, behind_person=true)` places that cut-out for you, one piece per
  clip under the scene and over exactly its time, on a Person track above it (`revise` with it adds the person to a
  scene already there); it does not follow a scene you later move or trim.
- `letitedit_code_scene` (create, revise, or `look`) returns the scene in place, drawn now with the person, captions
  and everything else around it, in a few seconds; it also says plainly when a page error, a blank scene or a frozen
  scene is the problem.
- `letitedit_check_frames` and `letitedit_check_range` show scenes too, so use them for the whole timeline; a frame
  labelled "NOT drawn" has a scene that could not be drawn, which is not an empty background.

## 6. Check at feed size
A Look with picture-coloured caption letters (one caption system, blend on the letters-only layer, any readability aid
on every caption): letitedit-captions' references/look-captions.md.
