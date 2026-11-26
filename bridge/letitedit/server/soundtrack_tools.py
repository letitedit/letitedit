"""MCP tool: a deliberate score from one song (soundtrack.py)."""
from __future__ import annotations

from pathlib import Path

import letitedit.sound.soundtrack as soundtrack

# what the MCP reply leaves out of the plan (it stays in the plan file: plan_file)
_BULKY = ('bar_grid',)


def _slim(res):
    out = {k: v for k, v in res.items() if k not in _BULKY}
    if isinstance(out.get('gain'), dict):
        out['gain'] = {k: v for k, v in out['gain'].items() if k != 'curve'}
        out['gain']['curve_points'] = len(res['gain'].get('curve') or [])
    if isinstance(out.get('speech'), dict):
        sp = dict(out['speech'])
        sp['spans'] = len(sp.get('spans') or [])
        sp['dips'] = sp.get('dips', [])[:40]
        out['speech'] = sp
    if out.get('plan_id'):
        out['plan_file'] = str(soundtrack._plan_path(out['plan_id']))
    return out


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_soundtrack(project: str | None = None, song: str | None = None, sections: list | None = None,
                           hits: list | None = None, protect: list | None = None, start: float | str | None = None,
                           end: float | str | None = None, repeat: dict | None = None, max_stretch: float = 0.0,
                           mode: str = 'plan', plan_id: str | None = None, track: str = 'Music',
                           levels: dict | None = None, ending: str = 'auto', entry: str = 'fade',
                           song_range: list | None = None, options: dict | None = None, force: bool = False,
                           background: bool = False) -> list:
        """A deliberate score from ONE song arranged around a project: music that builds, lands on a reveal, steps
        aside for natural sound, and never loops audibly. The song is cut into pieces on its own bar lines and laid
        on a music track as ordinary clips of the song file (referenced in place, never copied), joined by short
        Shotcut crossfades that end on the downbeat, with gain keyframes and audio fades the person can edit.
        mode: 'plan' (default; writes nothing to the project: the proposal, its edit ops and a picture),
        'apply' (with plan_id: applies that plan; without: plans and applies at once) - goes through the same
        apply as letitedit_timeline_apply (one undo step in an open Shotcut window, or the saved file with a history
        copy; letitedit_timeline_undo reverts it) and is REFUSED when the project, the song or the footage changed
        since the plan (force=true applies anyway); after applying, the mix is rendered with melt and measured.
        'measure' (plan_id): measure the project's current mix against that plan's ranges (after hand edits too).
        'song' (song only): the song's tempo, beat clarity, bars, phrase starts, drops, energy by bar and ending,
        to choose hit kinds and sections.
        Inputs (times are timeline seconds or 'm:ss.s'):
        - project: .mlt or episode/cut folder. song: a music file (e.g. from letitedit_library).
        - sections: [{from, to, energy: low | mid | high | 0-1, level?: dB vs the dialogue, name?}]: the energy of
          the song material picked for that stretch (bars are scored by loudness and onset density); the level
          defaults from the energy (levels below). Unlisted time takes any material and the 'none' level.
        - hits: [{at, kind, approach?, tolerance_ms?, song_at?, name?}] (or [at, kind] / a number): a musical event
          to land exactly at `at`. kind: 'downbeat' | 'bar' (any bar line), 'phrase' (a 4-bar phrase start or an
          energy-section start), 'drop' (a bar where the music gets 3 dB+ louder into a loud stretch; the biggest
          rise when the song has none), 'beat' (treated as a bar line). song_at: land that song time (its bar)
          instead. approach: 'auto' (cheapest of the below), 'join' (whole beats, the last cut short: a join right on
          the hit), 'stretch' (speed of the stretch before it changed by at most max_stretch; pitch moves with it),
          'break' (the music stops on a beat and silence leads into the hit), 'none' (no edit: reports where the
          nearest event of that kind lands). The music already landing within tolerance_ms (default 25) needs none.
        - protect: [{from, to, mode, level?, fade_out?, fade_in?, entry?, why?}]: natural sound that must stay clear (a
          machine running, a punchline). mode 'duck_deep': music held `level` dB under that range's own measured
          sound (default -20), and never less than 6 dB under the talk level; when that sound can't be measured,
          (level + 6) dB under the talk level (14 dB at the default); 'drop_out': the music fades
          out to finish at `from` (fade_out, default 1 s) and comes back at `to` (fade_in 0.5 s, entry 'fade' or
          'hard'), on a fresh phase, so a hit right after it can land free.
        - start / end: where the music starts and stops (default: the whole timeline). entry: 'fade' (fade in, may
          start mid-bar so the first hit lands) | 'hard' (on a downbeat). ending: 'auto' (the song's own ending when
          it has one and it fits, else a fade) | 'song' | 'fade' | 'stop' (ends on a bar line).
        - repeat: {max_uses (times any bar may play; default: as needed + 1), min_gap_s (default 20), loops (false:
          no block of up to loop_bars bars plays twice back to back), loop_bars (8)}.
        - max_stretch: 0-0.12, largest speed change for landing hits (0 = never; 0.02 moves the pitch 34 cents).
        - levels (dB vs the dialogue's loudness after the song is matched to it; with no talking, vs -14 LUFS):
          {talk -18, none -6, low -9, mid -6.5, high -4, duck_deep -20 (vs the natural sound)}.
        - song_range: [a, b] song seconds the material may come from. track: the music track (default 'Music',
          made if missing; its clips are replaced). options: crossfade_s 0.1, weak_crossfade_s 0.15,
          coarse_crossfade_s 1.5, fade_in_s 1.5, fade_out_s 3, drop_fade_out_s 1, drop_fade_in_s 0.5, break_fade_s
          0.1, tolerance_ms 25, attack_s 0.35, preroll_s 0.1, hold_s 0.3, release_s 1.0, merge_gap_s 4, section_ramp_s
          1, duck true (dip under speech; false for a montage whose shots only have background voices),
          beats_per_bar 4, beam 96, min_run_s 2, peak_ceiling_dbfs -2, preview_audio true,
          correct_engine_offsets true (after applying, pieces the render plays more than half a frame off the plan -
          a song file the engine seeks imprecisely, e.g. some VBR MP3s - get their in points shifted by whole
          frames as a second undo step, and the mix is measured again), match_placed_loudness false (true: the song
          is matched to the dialogue by the loudness of its bars placed rather than the whole song's, so the levels
          hold whichever passages are used).
        - background: true runs it as a background job (letitedit_jobs follows it); for long timelines.
        Returns the picture (sections, speech, protected ranges, hits with their error; which song time plays when;
        the level curve; after measuring, the measured music and programme loudness) and a dict:
        schema_version, plan_id, plan_file, project_revision, source_fingerprints (project hash, song size/time,
        analysis versions, the footage speech was measured on), song (tempo, beat_quality clear | weak | none with
        the measured clarity numbers; 'none' means only coarse ~2 s units: joins are long crossfades and hit times
        approximate), music span, settings (every value used), pieces [{id, timeline [start, end], song [in, out],
        bars, speed, enters, ends, energy}], joins [{at, from_song, to_song, from_on/to_on (downbeat | beat |
        between beats), crossfade_s, grid_error_ms (where the incoming downbeat falls against the outgoing piece's
        beat grid), why, cost, flam_risk?}], hits [{hit, at, kind, by (natural | join | stretch | break | entry |
        none), song, bar, event, lands_at, error_ms (planned, whole frames), fit {approach, bars, extra_beats, speed,
        pitch_cents, stop_s, trimmed_ms}, options_considered, without_edit {nearest_downbeat, off_ms}: where moving
        the picture cut would land with no music edit}], sections [{energy asked, target, got, song bars}], protect
        [{range, mode, natural_lufs, music level}], gain {base_gain_db, reference_lufs, song_lufs, segments},
        speech (detected, dips), repeats {bars used more than once, shortest reuse gap, back_to_back_loops}, search
        {cost (lower is smoother; not a probability), relaxed limits}, changes (the edit ops: add_track/delete/track/
        insert with {clip, in, out, speed?, transition, effects: gain keys, fade_in_audio, fade_out_audio}; send
        them to letitedit_timeline_apply yourself if you prefer), findings [{kind, severity, timeline, source?, text,
        measured}], checked_ranges, unchecked_ranges, warnings, unsupported, preview_artifacts {graph, music_bed:
        an mp3 of the planned bed alone}. After apply/measure also: applied {changes, history, undo}, readback (the
        track as written vs the plan), measurements {true_peak_dbtp, sample_peak_dbfs, integrated_lufs,
        music_integrated_lufs, speech {median/min music_under_lu over speech spans, spans under 10 / over 24 LU,
        closest}, protect [{music_peak_dbfs, music_lufs, natural_sound_lufs, music_under_natural_lu, verdict}],
        hits [{measured_error_ms, match}] (cross-correlation of the rendered music with the song), pieces [{id,
        offset_ms (where the render really plays each piece), shift_frames}], corrections (set ops, when pieces play
        off time), joins [{incoming_offset_ms, level_vs_plan_db (render against the planned signal before, in and
        after the crossfade)}], envelope_vs_plan (the gain keys as rendered), loops {edit_made, in_the_song},
        sections [{music_lufs}], findings, checked/unchecked ranges, files (mp3s of the music stem and the mix)};
        correction {changes, before, hits_before} when apply shifted pieces. Measurements cannot certify taste:
        listen."""
        inputs = {'project': project, 'song': song, 'sections': sections, 'hits': hits, 'protect': protect,
                  'start': start, 'end': end, 'repeat': repeat, 'max_stretch': max_stretch, 'mode': mode,
                  'plan_id': plan_id, 'track': track, 'levels': levels, 'ending': ending, 'entry': entry,
                  'song_range': song_range, 'options': options, 'force': force}
        try:
            if background:
                import letitedit.core.jobs as jobs
                label = f"soundtrack {mode}: {Path(str(song or plan_id or '')).stem[:40]}"
                return [{'job': jobs.submit('soundtrack:job', inputs, label=label),
                         'note': 'running in the background; letitedit_jobs shows its progress and result'}]
            res = soundtrack.soundtrack(**inputs)
        except (FileNotFoundError, ValueError) as e:
            return [{'error': str(e)}]
        res = _slim(res)
        graph = None
        meas = res.get('measurements') if isinstance(res.get('measurements'), dict) else None
        if meas and meas.get('graph'):
            graph = meas['graph']
        elif (res.get('preview_artifacts') or {}).get('graph'):
            graph = res['preview_artifacts']['graph']
        import letitedit.server.next_step_replies as next_step_replies     # T345 C2, behind its own switch
        res = next_step_replies.soundtrack_reply(res)
        if graph and Path(graph).exists():
            return [Image(data=Path(graph).read_bytes(), format='png'), res]
        return [res]

    return letitedit_soundtrack
