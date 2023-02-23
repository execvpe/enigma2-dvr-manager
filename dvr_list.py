#!/usr/bin/env python3

import cv2
import PySimpleGUI as sg
import sqlite3
import os
import re
import subprocess
import sys

# Enigma 2 video file extension (default: ".ts")
E2_VIDEO_EXTENSION = ".ts"
# As far as I know there are six files associated to each recording
E2_EXTENSIONS = [".eit", ".ts", ".ts.ap", ".ts.cuts", ".ts.meta", ".ts.sc"]

class Reason:
    def __init__(self, key: str, desc: str):
        self.key  = key
        self.desc = desc

    def __repr__(self) -> str:
        return self.desc

DROP_REASONS = [
    Reason("no",             "KEEP | NO DROP"),

    Reason("badrecording",   "Bad recording | Empty file | etc."),

    Reason("beginmissing",   "Missing beginning"),
    Reason("endmissing",     "Missing end"),

    Reason("advertising",    "Advertising banner"),
    Reason("watermark",      "Watermark"),
    Reason("mutilated",      "Aired too early | Wrong age restriction"),

    Reason("mastered",       "Already mastered"),
    Reason("redundant",      "Redundant | Better recording available"),

    Reason("unwanted",       "Unwanted recording"),
    Reason("unknown",        "Unknown reason"),
]

recordings = []
window = None
database = sqlite3.connect("rec_cache.db")
class Recording:
    def __getattributes(rec) -> str:
        return f"{'D' if rec.drop_reason != 'no' else '.'}{'G' if rec.is_good else '.'}{'M' if rec.is_mastered else '.'}"

    def __repr__(rec) -> str:
        return f"{rec.__getattributes()} | {rec.date_str} {rec.time_str} | {(to_GiB(rec.file_size)):4.1f} GiB | {(rec.video_duration // 60):3d} min | {rec.epg_channel[:10].ljust(10)} | {rec.epg_title[:42].ljust(42)} | {rec.epg_description}"

class RecordingFactory:
    @staticmethod
    def from_meta_file(basepath: str, meta: list[str]) -> Recording:
        rec = Recording()

        rec.basepath = basepath

        rec.file_basename, rec.file_size = os.path.basename(basepath), os.stat(basepath + E2_VIDEO_EXTENSION).st_size
        rec.epg_channel, rec.epg_title = meta[0].split(":")[-1].strip(), meta[1].strip()
        rec.epg_description = remove_prefix(meta[2].strip(), rec.epg_title).strip()
        rec.video_duration, rec.video_height, rec.video_width, rec.video_fps = get_video_metadata(rec)
        rec.is_good, rec.drop_reason, rec.is_mastered = False, "no", False

        if len(rec.epg_channel) == 0:
            rec.epg_title = basepath.split(" - ")[1] + "[?]";
        if len(rec.epg_title) == 0:
            rec.epg_title = basepath.split(" - ")[2] + "[?]"

        RecordingFactory.__both(rec)
        return rec

    @staticmethod
    def from_database(basepath: str) -> Recording:
        basename = os.path.basename(basepath)
        rec = db_load(basename)
        if rec == None:
            return None

        assert rec.file_size == os.stat(basepath + E2_VIDEO_EXTENSION).st_size

        rec.basepath = basepath

        RecordingFactory.__both(rec)
        return rec

    @staticmethod
    def __both(rec: Recording) -> None:
        splitname = rec.file_basename.split(" ")

        rec.date_str = f"{splitname[0][:4]}-{splitname[0][4:6]}-{splitname[0][6:8]}"
        rec.time_str = f"{splitname[1][:2]}:{splitname[1][2:4]}"
        rec.sortkey  = alphanumeric(f"{rec.epg_title}{rec.time_str}").lower()

# Remove everything that is not a letter or digit
def alphanumeric(line: str) -> str:
    return re.sub("[^A-Za-z0-9]+", "", line)

def remove_prefix(line: str, prefix: str) -> str:
    return re.sub(f"^{re.escape(prefix)}", "", line)

def to_GiB(size: int) -> float:
    return size / 1_073_741_824

def drop_recording(rec: Recording) -> None:
    for e in E2_EXTENSIONS:
        filepath = rec.basepath + e
        if os.path.exists(filepath):
            print(filepath)
    db_remove(rec)

def update_attribute(recs: list[Recording], check, update) -> None:
    if len(recs) == 0:
        return
    for r in recs:
        if check(r):
            update(r)
            gui_update_item(r)
            db_save(r)
    window["listbox"].widget.selection_clear(0, len(recordings))

def get_video_metadata(rec: Recording) -> (int, int, int, int):
    vid = cv2.VideoCapture(rec.basepath + E2_VIDEO_EXTENSION)

    fps    = int(vid.get(cv2.CAP_PROP_FPS))
    frames = int(vid.get(cv2.CAP_PROP_FRAME_COUNT))
    height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
    width  = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))

    vid.release()

    duration = frames // fps if fps != 0 else -1

    return (duration, height, width, fps)

def gui_init() -> None:
    sg.ChangeLookAndFeel("Dark Black")

    gui_layout = [[sg.Text(key="selectionTxt",
                          font=("JetBrains Mono", 14)),
                   sg.Push(), sg.Button("Drop", key="dropBtn")],
                  [sg.Text("[D]rop / Change reason, [K]eep | [O]pen in VLC | Mark as [G]ood, [B]ad (normal)",
                           font=("JetBrains Mono", 14), text_color="grey")],
                  [sg.Text(key="metaTxt",
                           font=("JetBrains Mono", 14), text_color="yellow")],
                  [sg.Listbox(key="listbox",
                              values=recordings,
                              size=(1280, 720),
                              enable_events=True,
                              font=("JetBrains Mono", 14),
                              select_mode=sg.LISTBOX_SELECT_MODE_EXTENDED)]]

    global window
    window = sg.Window(title="DVR Duplicates",
                       layout=gui_layout,
                       return_keyboard_events=True,
                       resizable=True,
                       finalize=True)

def gui_recolor(window: sg.Window) -> None:
    for i, r in enumerate(recordings):
        if r.drop_reason != "no":
            window["listbox"].widget.itemconfig(i, fg="white", bg="red")
            continue

        if r.is_mastered:
            window["listbox"].widget.itemconfig(i, fg="white", bg="blue")
            continue

        if r.is_good:
            window["listbox"].widget.itemconfig(i, fg="black", bg="light green")
            continue

        window["listbox"].widget.itemconfig(i, fg="white", bg="black")

def gui_update_item(rec: Recording) -> None:
    i = recordings.index(rec)
    window["listbox"].widget.delete(i)
    window["listbox"].widget.insert(i, rec)
    window["listbox"].widget.selection_set(i)

def ask_reason() -> str:
    selection_layout = [[sg.Listbox(key="selectionbox",
                                    values=DROP_REASONS,
                                    size=(64, 10),
                                    font=("JetBrains Mono", 14),
                                    bind_return_key=True,
                                    select_mode=sg.LISTBOX_SELECT_MODE_BROWSE)
                         ]]

    selection = sg.Window(title="Choose a drop reason",
                          layout=selection_layout,
                          relative_location=(25, 25),
                          modal=True,
                          finalize=True)

    selection["selectionbox"].widget.config(fg="white", bg="black")
    selection["selectionbox"].widget.selection_set(0)
    selection.force_focus()
    selection["selectionbox"].set_focus()
    while True:
        event, _ = selection.read()

        if event == sg.WIN_CLOSED:
            return None

        items = selection["selectionbox"].get()
        if len(items) == 1:
            selection.close()
            return items[0].key

def db_init() -> None:
    c = database.cursor()
    c.execute("""
              CREATE TABLE IF NOT EXISTS
                recordings(file_basename VARCHAR PRIMARY KEY, file_size INT,
                  epg_channel VARCHAR, epg_title VARCHAR, epg_description VARCHAR,
                   video_duration INT, video_height INT, video_width INT, video_fps INT,
                   is_good BOOL, drop_reason VARCHAR, is_mastered BOOL);
              """)

def db_load(basename: str) -> Recording:
    c = database.cursor()
    c.execute("""
              SELECT file_basename, file_size,
                epg_channel, epg_title, epg_description,
                video_duration, video_height, video_width, video_fps,
                is_good, drop_reason, is_mastered
              FROM recordings
              WHERE file_basename = ?;
              """, (basename, ))
    raw = c.fetchone()

    if raw == None:
        return None

    rec = Recording()
    rec.file_basename, rec.file_size = raw[0], int(raw[1])
    rec.epg_channel, rec.epg_title, rec.epg_description = raw[2], raw[3], raw[4]
    rec.video_duration, rec.video_height, rec.video_width, rec.video_fps = raw[5], raw[6], raw[7], raw[8]
    rec.is_good, rec.drop_reason, rec.is_mastered = bool(raw[9]), raw[10], bool(raw[11])

    return rec

def db_save(rec: Recording) -> None:
    db_remove(rec)
    c = database.cursor()
    c.execute("""
              INSERT INTO recordings(file_basename, file_size,
                epg_channel, epg_title, epg_description,
                video_duration, video_height, video_width, video_fps,
                is_good, drop_reason, is_mastered)
              VALUES (?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?);
              """, (rec.file_basename, rec.file_size,
              rec.epg_channel, rec.epg_title, rec.epg_description,
              rec.video_duration, rec.video_height, rec.video_width, rec.video_fps,
              rec.is_good, rec.drop_reason, rec.is_mastered))

    database.commit()

def db_remove(rec: Recording):
    c = database.cursor()
    c.execute("""
              DELETE FROM recordings
              WHERE file_basename = ?
              """, (rec.file_basename, ))

    assert c.rowcount <= 1
    database.commit()

def all_recordings_in(dirpath: str) -> list[str]:
    all_files = []
    try:
        for f in os.listdir(dirpath):
            filepath = os.path.join(dirpath, f)

            if os.path.isdir(filepath):
                all_files += all_recordings_in(filepath)
                continue

            if not os.path.isfile(filepath):
                continue

            if f.endswith(E2_VIDEO_EXTENSION):
                all_files.append(filepath)
    except PermissionError:
        pass

    return all_files

def main(argc: int, argv: list[str]) -> None:
    if argc < 2:
        raise IndexError(f"Usage: {argv[0]} <dir path> [dir path ...]")

    db_init()

    print("Scanning directories... (This may take a while)", file=sys.stderr)

    filenames = []
    for i, d in enumerate(argv[1:]):
        print(f"Scanning directory: {i + 1} of {argc - 1}", end="\r", file=sys.stderr)
        filenames += all_recordings_in(d)

    print(f"Successfully scanned {argc - 1} directories.", file=sys.stderr)

    print("Processing recordings... (This may take a while)", file=sys.stderr)

    db_count = 0
    for i, f in enumerate(filenames):
        print(f"Processing recording {i + 1} of {len(filenames)}", end="\r", file=sys.stderr)
        basepath = re.sub("\.ts$", "", f)
        rec = RecordingFactory.from_database(basepath)
        if rec != None:
            recordings.append(rec)
            db_count += 1
            continue
        try:
            with open(f + ".meta", "r", encoding="utf-8") as m:
                rec = RecordingFactory.from_meta_file(basepath, m.readlines())
                db_save(rec)
                recordings.append(rec)
        except FileNotFoundError:
            print(f"{f}.meta not found! Skipping...", file=sys.stderr)

    print(f"Successfully processed {len(filenames)} recordings. ({db_count} in cache, {len(filenames) - db_count} new)", file=sys.stderr)

    print("Sorting...", file=sys.stderr)
    recordings.sort(key=lambda r: r.sortkey)
    print("Finished sorting.", file=sys.stderr)

    gui_init()
    window["listbox"].set_focus()
    window["listbox"].widget.config(fg="white", bg="black")

    while True:
        selected_recodings = [r for r in recordings if r.drop_reason != "no"]
        good_recodings = [r for r in recordings if r.is_good]

        window["selectionTxt"].update(f"{len(selected_recodings)} item(s) (approx. {to_GiB(sum([r.file_size for r in selected_recodings])):.1f} GiB) selected for drop | {len(good_recodings)} recordings good | {len(recordings)} total")

        gui_recolor(window)
        event, _ = window.read()

        if event == sg.WIN_CLOSED:
            quit()

        listbox_selected_rec = window["listbox"].get()

        if len(listbox_selected_rec) > 0:
            r = listbox_selected_rec[0]
            window["metaTxt"].update(f"{r.video_width:4d}x{r.video_height:4d}#{r.video_fps} | Drop: {r.drop_reason} | Base: {r.file_basename}")

        # [O]pen recording using VLC
        if event == "o:32" and len(listbox_selected_rec) > 0:
            subprocess.Popen(["/usr/bin/env", "vlc", listbox_selected_rec[0].basepath + E2_VIDEO_EXTENSION])
            continue

        # Select for [D]rop or change reason
        if event == "d:40":
            reason_key = ask_reason()
            update_attribute(listbox_selected_rec,
                             lambda r: not r.is_mastered,
                             lambda r: setattr(r, "drop_reason", reason_key))
            continue

        # [K]eep from Drop
        if event == "k:45":
            update_attribute(listbox_selected_rec, lambda r: r.drop_reason != "no", lambda r: setattr(r, "drop_reason", "no"))
            continue

        # Mark recording as [G]ood
        if event == "g:42":
            update_attribute(listbox_selected_rec, lambda r: not r.is_good, lambda r: setattr(r, "is_good", True))
            continue

        # Mark recording as [B]ad (normal)
        if event == "b:56":
            update_attribute(listbox_selected_rec, lambda r: r.is_good, lambda r: setattr(r, "is_good", False))
            continue

        # Drop button pressed
        if event == "dropBtn":
            for_deletion = set()
            for r in [x for x in recordings if x.drop_reason != "no"]:
                drop_recording(r)
                for_deletion.add(r)
            for r in for_deletion:
                recordings.remove(r)
            window["listbox"].update(recordings)

if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
