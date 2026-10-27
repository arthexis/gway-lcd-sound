# Sound motif authoring

The installed `sound` executable owns source motifs, playback and SQLite persistence.
No helper daemon, wrapper or direct database editing is needed.

```sh
sound motif validate --notes '[[440,0.06,0.02],[0,0.04,0]]' --cooldown-seconds 30
sound motif preview --notes '[[440,0.06,0.02],[0,0.04,0]]' --dry-run
sound motif preview --notes '[[440,0.06,0.02],[0,0.04,0]]' --backend gpio
sound motif set custom-source --notes '[[440,0.06,0.02],[0,0.04,0]]' --cooldown-seconds 30
sound motif show custom-source
sound motif list
sound motif remove custom-source
```

Output is deterministic JSON; errors exit nonzero. Only `set` and `remove`
modify motif definitions. Preview never opens the event database; `--dry-run`
does not call the playback backend. Frequency 0 is a rest (silent duration).
One to twelve notes are allowed. Each note is `[frequency_hz, duration_seconds,
pause_seconds]`; frequency is 0 or 80–4000 Hz, duration 0.01–0.4 s and
pause 0–0.4 s. Cooldown is 0–3600 s.

Sources are lowercase ASCII identifiers beginning with a letter, followed by
letters, digits or hyphens (at most 64 characters). The `github-*` aliases
share the `github` motif, so aliases cannot be saved independently.
Built-in motifs can be updated but cannot be removed. To roll back an edit,
save the previous `show` JSON notes/cooldown with `set`; a custom motif
can be removed with `remove`. Existing `--pattern-json`, `--motif`,
`--list-motifs` and source-event playback remain supported.

A saved source motif plays before the mapped event earcon when the source
changes or its cooldown expires. Validate on actual audio hardware separately:
CI, previews with `--dry-run`, and install should produce no GPIO audio.
