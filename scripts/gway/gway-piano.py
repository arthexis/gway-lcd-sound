#!/usr/bin/env python3
"""Terminal-first monophonic earcon composer; no third-party dependencies."""
import argparse
import curses
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

DB_DEFAULT = Path(os.environ.get("GWAY_SOUND_EVENT_DB", str(Path.home()/".local/state/gway-sound/events.sqlite3")))
KEYS = {"a":0,"w":1,"s":2,"e":3,"d":4,"f":5,"t":6,"g":7,"y":8,"h":9,"u":10,"j":11,"k":12}
NAMES = ("C","C#","D","D#","E","F","F#","G","G#","A","A#","B")
MAX_NOTES = 12
MAX_DURATION = 400
MAX_PAUSE = 400

def pitch(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)

def label(hz):
    if hz <= 0:
        return "REST"
    midi = round(69 + 12 * math.log2(hz / 440))
    return f"{NAMES[midi % 12]}{midi//12-1}"

def validate(notes):
    if not 1 <= len(notes) <= MAX_NOTES:
        raise ValueError("composition requires 1-12 steps")
    normalized = []
    for item in notes:
        if len(item) != 3:
            raise ValueError("steps need [Hz, seconds, pause_seconds]")
        hz, duration, pause = (float(v) for v in item)
        if not all(math.isfinite(v) for v in (hz,duration,pause)):
            raise ValueError("values must be finite")
        if not (hz == 0 or 80 <= hz <= 4000):
            raise ValueError("frequency must be 0 (rest) or 80-4000 Hz")
        if not (0.01 <= duration <= 0.4 and 0 <= pause <= 0.4):
            raise ValueError("duration must be 10-400 ms, pause 0-400 ms")
        normalized.append([hz, duration, pause])
    return normalized

def db_open(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_mode & 0o077:
        raise ValueError("event database directory must be private")
    if path.is_symlink():
        raise ValueError("database cannot be a symlink")
    created = not path.exists()
    conn = sqlite3.connect(path)
    if created: os.chmod(path, 0o600)
    if path.stat().st_mode & 0o077:
        conn.close()
        raise ValueError("database permissions must be 0600")
    conn.execute("CREATE TABLE IF NOT EXISTS motifs (source TEXT PRIMARY KEY, notes TEXT NOT NULL, cooldown_seconds REAL NOT NULL DEFAULT 45)")
    conn.execute("CREATE TABLE IF NOT EXISTS sounds (name TEXT PRIMARY KEY, notes TEXT NOT NULL)")
    return conn

def safe_name(name):
    name = name.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("name must have 1-64 lowercase letters, digits, _ or -")
    return "github" if name == "github" or name.startswith("github-") else name

def save(path, kind, name, notes, cooldown=45, overwrite=False):
    notes = validate(notes)
    name = safe_name(name)
    if not 0 <= cooldown <= 3600:
        raise ValueError("cooldown must be 0-3600 seconds")
    table, field = ("motifs", "source") if kind == "motif" else ("sounds", "name")
    with db_open(path) as db:
        existing = db.execute(f"SELECT 1 FROM {table} WHERE {field}=?", (name,)).fetchone()
        if existing and not overwrite:
            raise ValueError(f"{kind} '{name}' already exists; use --overwrite")
        if kind == "motif":
            db.execute("INSERT INTO motifs(source,notes,cooldown_seconds) VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET notes=excluded.notes,cooldown_seconds=excluded.cooldown_seconds", (name,json.dumps(notes),cooldown))
        else:
            db.execute("INSERT INTO sounds(name,notes) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET notes=excluded.notes", (name,json.dumps(notes)))

def load(path, kind, name):
    name = safe_name(name)
    table, field = ("motifs","source") if kind=="motif" else ("sounds","name")
    with db_open(path) as db:
        row = db.execute(f"SELECT notes FROM {table} WHERE {field}=?", (name,)).fetchone()
    if not row:
        raise ValueError(f"no such {kind}: {name}")
    return validate(json.loads(row[0]))

def inventory(path, kind):
    table, field = ("motifs","source") if kind=="motif" else ("sounds","name")
    with db_open(path) as db:
        return [r[0] for r in db.execute(f"SELECT {field} FROM {table} ORDER BY {field}")]

def play(notes, args):
    script = Path(__file__).resolve().with_name("sound.sh")
    if not script.exists():
        raise RuntimeError("sound.sh not installed alongside piano")
    subprocess.run([str(script), "--pattern-json", json.dumps(validate(notes)), "--backend", args.backend,
                    "--volume", str(args.volume), *(["--dry-run"] if args.dry_run else [])], check=True)

def export_file(path, notes):
    # Pure data for portable import, no code evaluation.
    target = Path(path)
    if target.exists():
        raise ValueError("export destination exists")
    with target.open("x", encoding="utf-8") as stream:
        json.dump({"format":"gway-piano-v1","notes":validate(notes)},stream,indent=2)
        stream.write("\n")

def import_file(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data,dict) or data.get("format") != "gway-piano-v1":
        raise ValueError("unknown composition format")
    return validate(data["notes"])

class Editor:
    def __init__(self, args):
        self.args=args
        self.notes=[]
        self.cursor=0
        self.octave=5
        self.duration=100
        self.pause=40
        self.record=False
        self.undo=[]
        self.message="Press A-K to audition; R to record; ? for keys."
        if args.load:
            self.notes=load(args.event_db,args.kind,args.load)
            self.message=f"Loaded {args.kind} {args.load}"
    def snapshot(self):
        self.undo.append([x[:] for x in self.notes])
        self.undo=self.undo[-50:]
    def insert(self, hz):
        if len(self.notes)>=MAX_NOTES:
            self.message="12-step maximum (production motif contract)"
            return
        self.snapshot()
        self.notes.insert(self.cursor,[float(hz),self.duration/1000,self.pause/1000])
        self.cursor=min(len(self.notes)-1,self.cursor+1)
    def render(self, scr):
        scr.erase()
        height,width=scr.getmaxyx()
        rows=[
          "GWAY PIANO  |  event / motif composer  |  monophonic",
          f"Octave: {self.octave}  Duration: {self.duration} ms  Pause: {self.pause} ms  Record: {'ON' if self.record else 'OFF'}",
          "Keyboard: A W S E D F T G Y H U J K  |  -/= octave  |  R record",
          "Arrows: select note; Up/Down pitch semitone  |  [/] duration +/-10 ms",
          ",/. pause +/-10 ms | Shift+I rest | Shift+X remove | Shift+U undo",
          "Space play | Shift+S save | Shift+O export | Shift+L import | ? help | Shift+Q quit",
          "",
          " #   NOTE       FREQUENCY (Hz)   DURATION (ms)   PAUSE (ms)",
        ]
        for i,(hz,d,p) in enumerate(self.notes):
            rows.append(f"{'>' if i==self.cursor else ' '} {i+1:2d}  {label(hz):<9}  {hz:>14.3f}    {d*1000:>10.1f}    {p*1000:>10.1f}")
        if self.notes:
            rows.append(f"Total duration: {sum(n[1]+n[2] for n in self.notes)*1000:.1f} ms")
        rows+=["", self.message]
        for y,row in enumerate(rows[:height-1]):
            try: scr.addnstr(y,0,row,max(0,width-1))
            except curses.error: pass
        scr.refresh()
    def prompt(self,scr,label_,default=""):
        h,w=scr.getmaxyx()
        curses.echo()
        try:
            scr.move(h-1,0);scr.clrtoeol()
            scr.addnstr(h-1,0,label_+" ["+default+"]: ",max(0,w-1))
            s=scr.getstr(h-1,min(w-1,len(label_)+len(default)+5),80).decode().strip()
            return s or default
        finally: curses.noecho()
    def run(self,scr):
        curses.curs_set(0)
        scr.keypad(True)
        while True:
            self.render(scr)
            key=scr.getch()
            try:
                if key in (ord("q"),27):
                    if self.notes and self.prompt(scr,"Unsaved changes; type QUIT to exit","") != "QUIT":
                        continue
                    return
                if key in (curses.KEY_LEFT,curses.KEY_RIGHT):
                    self.cursor=max(0,min(len(self.notes)-1,self.cursor+(-1 if key==curses.KEY_LEFT else 1)))
                elif key in (ord("r"),):
                    self.record=not self.record
                elif key in (ord("-"),ord("=")):
                    self.octave=max(1,min(8,self.octave+(-1 if key==ord("-") else 1)))
                elif key in (ord("["),ord("]")):
                    self.duration=max(10,min(400,self.duration+(-10 if key==ord("[") else 10)))
                elif key in (ord(","),ord(".")):
                    self.pause=max(0,min(400,self.pause+(-10 if key==ord(",") else 10)))
                elif key in (ord("I"),):
                    self.insert(0)
                elif key in (ord("X"),curses.KEY_BACKSPACE,127):
                    if self.notes:
                        self.snapshot();self.notes.pop(self.cursor);self.cursor=max(0,min(self.cursor,len(self.notes)-1))
                elif key in (ord("U"),):
                    if self.undo:
                        self.notes=self.undo.pop();self.cursor=max(0,min(self.cursor,len(self.notes)-1))
                elif key in (curses.KEY_UP,curses.KEY_DOWN) and self.notes:
                    old=self.notes[self.cursor][0]
                    if old:
                        midi=round(69+12*math.log2(old/440))+(1 if key==curses.KEY_UP else -1)
                        hz=pitch(midi)
                        if 80<=hz<=4000:
                            self.snapshot();self.notes[self.cursor][0]=hz
                elif key==ord(" "):
                    if self.notes: play(self.notes,self.args)
                elif key==ord("S"):
                    if not self.notes: continue
                    kind=self.prompt(scr,"Type motif or sound",self.args.kind)
                    if kind not in ("motif","sound"): raise ValueError("type must be motif or sound")
                    name=self.prompt(scr,"Name",self.args.load or "")
                    cooldown=float(self.prompt(scr,"Cooldown seconds","45")) if kind=="motif" else 45
                    confirm=self.prompt(scr,"Overwrite existing? type YES to permit","")
                    save(self.args.event_db,kind,name,self.notes,cooldown,overwrite=confirm=="YES")
                    self.message=f"Saved {kind} {name}"
                    self.args.load=name
                    self.args.kind=kind
                elif key==ord("O"):
                    export_file(self.prompt(scr,"Export new JSON filename","composition.json"),self.notes)
                    self.message="Exported"
                elif key==ord("L"):
                    self.snapshot()
                    self.notes=import_file(self.prompt(scr,"JSON file path"))
                    self.cursor=0
                    self.message="Imported"
                elif key==ord("?"):
                    self.message="12 notes max. Rest=0 Hz. Save will not change event mappings. Preview won't change context."
                elif 0<=key<256 and chr(key) in KEYS:
                    hz=pitch((self.octave+1)*12+KEYS[chr(key)])
                    if 80<=hz<=4000:
                        play([[hz,self.duration/1000,0]],self.args)
                        if self.record:self.insert(hz)
                else:
                    continue
            except (OSError,ValueError,subprocess.CalledProcessError,sqlite3.Error) as exc:
                self.message=f"Error: {exc}"

def main(argv=None):
    p=argparse.ArgumentParser(description="GWAY interactive piano and motif/event earcon editor")
    p.add_argument("--kind",choices=("motif","sound"),default="motif")
    p.add_argument("--load",help="load existing named composition")
    p.add_argument("--event-db",default=str(DB_DEFAULT))
    p.add_argument("--backend",choices=("gpio","audio"),default="gpio")
    p.add_argument("--volume",type=float,default=0.42)
    p.add_argument("--dry-run",action="store_true")
    p.add_argument("--list",action="store_true")
    p.add_argument("--import-file",metavar="PATH")
    p.add_argument("--export-file",metavar="PATH")
    args=p.parse_args(argv)
    try:
        if args.list:
            print("\n".join(inventory(args.event_db,args.kind)))
            return 0
        if args.export_file:
            if not args.load: p.error("--export-file requires --load")
            export_file(args.export_file,load(args.event_db,args.kind,args.load))
            return 0
        if args.import_file and args.load:
            p.error("--import-file cannot be combined with --load")
        editor=Editor(args)
        if args.import_file:
            editor.notes=import_file(args.import_file)
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            p.error("interactive piano requires a TTY; use --list or --export-file headlessly")
        curses.wrapper(editor.run)
        return 0
    except (ValueError,sqlite3.Error,OSError) as exc:
        p.exit(1,f"piano: {exc}\n")

if __name__=="__main__":
    raise SystemExit(main())
