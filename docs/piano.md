# Piano — terminal composition on GWay-001

The `gway-lcd-sound piano` command is a local curses application. It requires a
TTY and does not expose any web or Android service.

## Run

```sh
gway-lcd-sound piano
gway-lcd-sound piano --kind motif --load github
gway-lcd-sound piano --kind sound --load ready
gway-lcd-sound piano --backend audio
gway-lcd-sound piano --kind motif --list
gway-lcd-sound piano --kind motif --load github --export-file github.json
gway-lcd-sound piano --import-file github.json
```

Interactive controls:

- A W S E D F T G Y H U J K: piano keys; each key plays immediately.
- R: toggle recording. Recorded keypresses insert sequential notes.
- - / =: change octave; [ / ]: change new note duration by 10 ms;
  , / .: change following pause by 10 ms.
- Left / Right: select step; Up / Down: transpose selected step by one semitone.
- Shift+I: insert rest, Shift+X: delete selected step, Shift+U: undo.
- Space: preview sequence, Shift+S: save motif/event sound,
  Shift+O: export JSON, Shift+L: import JSON, Shift+Q: quit.
- ? for an in-app help reminder.

Every row displays **frequency in Hz (three decimals)**, **duration in
milliseconds**, and **pause in milliseconds**, plus the nearest musical
pitch name. A rest is 0 Hz. The total duration is displayed in milliseconds.
A note is stored as `[frequency_hz, duration_seconds, pause_seconds]`, so
the display is a conversion, not a change to the persisted engine format.

Production compatibility limits: 1–12 steps, notes of 80–4000 Hz or a rest
at 0 Hz, 10–400 ms duration, and 0–400 ms pause. Source motifs use the
existing `motifs` table and 0–3600 second cooldown; named event sounds
use a new `sounds` table in the same SQLite database. Saving an event
sound **does not automatically map an event** to it.

The editor prompts before replacing an existing composition. Export never
overwrites an existing JSON file. Import validates a versioned data-only
format. Preview runs via the same `sound.sh` tone backend but never updates
motif context or event mappings.

**Deployment note:** The existing `gway-lcd-sound` release installs the
dispatcher and its adjacent `sound.sh` script, but does not replace the
host's independent `/usr/local/bin/sound`. Custom event sounds only become
active for external producers after that host sound entry point is
separately migrated to a compatible version. Do not replace it implicitly.
