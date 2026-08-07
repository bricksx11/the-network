# Music library

Empty by design — this needs real, properly licensed royalty-free tracks added by hand
before `render_video`/`orchestrator.py` can run for real. `find_music_track()` in
`src/orchestrator.py` will raise a clear error rather than silently substituting a
placeholder tone if this directory has nothing in it, on purpose: shipping unlicensed or
no audio to real accounts without anyone noticing would be worse than a loud failure here.

## Adding a track

1. Source something genuinely royalty-free / properly licensed for commercial use (not just
   "free download" — read the actual license terms).
2. Drop the audio file under `assets/music/<mood-or-genre>/`.
3. Add a `LICENSE.txt` next to it (or in the same folder, one per track) noting the source,
   license type, and any attribution requirement — so this is auditable later, not just
   "some MP3 someone added once."
4. `find_music_track()` picks randomly among whatever's here at render time — no other
   wiring needed once a track is in place.

Recognized extensions: `.mp3`, `.m4a`, `.wav`, `.aac`.
