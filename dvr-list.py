#!/usr/bin/env python3

import cv2
import glob
import PySimpleGUI as sg
import os
import re
import subprocess
import sys

# Enigma 2 video file extension (default: ".ts")
E2_VIDEO_EXTENSION = ".ts"
# As far as I know there are six files associated to each recording
E2_EXTENSIONS = [".eit", ".ts", ".ts.ap", ".ts.cuts", ".ts.meta", ".ts.sc"]
# Custom metadata file extension used by this software
DUP_META_EXTENSION = ".dupmeta"

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

class Recording:
    def __init__(self, basepath: str, meta: str):
        self.basepath    = basepath.strip()
        self.channel     = meta[0].split(":")[-1].strip()
        self.title       = meta[1].strip()

        if len(self.title) == 0:
            self.title = "[?] " + self.basepath.split(" - ")[2]

        self.description = remove_prefix(meta[2].strip(), self.title).strip()

        basename   = os.path.basename(self.basepath).split(" ")

        self.date        = f"{basename[0][:4]}-{basename[0][4:6]}-{basename[0][6:8]}"
        self.time        = f"{basename[1][:2]}:{basename[1][2:4]}"
        self.hd          = "HD" in self.channel.upper()
        self.sortkey     = alphanumeric(f"{self.title}{self.time}").lower()
        self.rec_size    = os.stat(basepath + E2_VIDEO_EXTENSION).st_size

        dupmeta = load_dupmeta(self)

        self.drop        =     dupmeta.get("drop",     "no")

#       assert len([x for x in DROP_REASONS if x.key == self.drop_reason_key]) == 1

        self.good        =     dupmeta.get("good",     None) == "True"
        self.mastered    =     dupmeta.get("mastered", None) == "True"
        self.duration    = int(dupmeta.get("duration", None))

        if self.duration == None:
            self.duration = get_video_duration(self)
            save_dupmeta(self)

    def __getattributes(self) -> str:
        return f"{'D' if self.drop != 'no' else '.'}{'G' if self.good else '.'}{'M' if self.mastered else '.'}"

    def __repr__(self) -> str:
        return f"{self.__getattributes()} | {self.date} {self.time} | {(to_GiB(self.rec_size)):4.1f} GiB | {(self.duration // 60):3d} min | {self.channel[:10].ljust(10)} | {self.title[:42].ljust(42)} | {self.description}"

# Remove everything that is not a letter or digit
def alphanumeric(line: str) -> str:
    return re.sub("[^A-Za-z0-9]+", "", line)

def remove_prefix(line: str, prefix: str) -> str:
    return re.sub(f"^{re.escape(prefix)}", "", line)

def to_GiB(size: int) -> float:
    return size / 1_073_741_824

def drop_recording(rec: Recording) -> None:
    for e in E2_EXTENSIONS + [DUP_META_EXTENSION]:
        filepath = rec.basepath + e
        if os.path.exists(filepath):
            print(filepath)

def load_dupmeta(rec: Recording) -> dict[str, str]:
    if not os.path.exists(rec.basepath + DUP_META_EXTENSION):
        return dict()
    with open(rec.basepath + DUP_META_EXTENSION, "r", encoding="utf-8") as f:
        return dict([x.strip().split("=") for x in f.readlines()])

def save_dupmeta(rec: Recording) -> None:
    with open(rec.basepath + DUP_META_EXTENSION, "w", encoding="utf-8") as f:
        f.write(f"duration={rec.duration}\ngood={rec.good}\ndrop={rec.drop}\nmastered={rec.mastered}\n")

def update_attribute(recs: list[Recording], check, update) -> None:
    if len(recs) == 0:
        return
    for r in recs:
        if check(r):
            update(r)
            update_listbox_item(r)
            save_dupmeta(r)
    window["listbox"].widget.selection_clear(0, len(recordings))

def get_video_duration(rec: Recording) -> int:
    vid     = cv2.VideoCapture(rec.basepath + E2_VIDEO_EXTENSION)
    fps     = int(vid.get(cv2.CAP_PROP_FPS))
    frames  = int(vid.get(cv2.CAP_PROP_FRAME_COUNT))
    vid.release()

    if fps == 0:
        return -1
    return frames // fps

def init_gui() -> None:
    sg.ChangeLookAndFeel("Dark Black")

    gui_layout = [[sg.Text("Please select an item...", key="selectionTxt",
                          font=("JetBrains Mono", 14)),
                   sg.Push(), sg.Button("Drop", key="dropBtn")],
                  [sg.Text("[D]rop / Change reason, [K]eep | [O]pen in VLC | Mark as [G]ood, [B]ad (normal)",
                           font=("JetBrains Mono", 14), text_color="grey")],
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

def recolor_gui(window: sg.Window) -> None:
    for i, r in enumerate(recordings):
        if r.drop != "no":
            window["listbox"].widget.itemconfig(i, fg="white", bg="red")
            continue

        if r.mastered:
            window["listbox"].widget.itemconfig(i, fg="white", bg="blue")
            continue

        if r.good:
            window["listbox"].widget.itemconfig(i, fg="black", bg="light green")
            continue

        window["listbox"].widget.itemconfig(i, fg="white", bg="black")

def update_listbox_item(rec: Recording) -> None:
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

def main(argc: int, argv: list[str]) -> None:
    if argc < 2:
        raise IndexError(f"Usage: {argv[0]} <dir path> [dir path ...]")

    print("Scanning directories... (This may take a while)", file=sys.stderr)
    filenames = []
    for i, d in enumerate(argv[1:]):
        path = d + "/*" + E2_VIDEO_EXTENSION
        print(f"Scanning directory: {i + 1} of {argc - 1}", end="\r", file=sys.stderr)
        filenames += glob.glob(path)
    print(f"Successfully scanned {argc - 1} directories.", file=sys.stderr)

    print("Reading meta files... (This may take a while)", file=sys.stderr)
    for i, f in enumerate(filenames):
        with open(f + ".meta", "r", encoding="utf-8") as m:
            print(f"Scanning meta file {i + 1} of {len(filenames)}", end="\r", file=sys.stderr)
            recordings.append(Recording(re.sub("\.ts$", "", f), m.readlines()))
    print(f"Successfully read {len(filenames)} meta files.", file=sys.stderr)

    print("Sorting...", file=sys.stderr)
    recordings.sort(key=lambda r: r.sortkey)
    print("Finished sorting.", file=sys.stderr)

    init_gui()
    window["listbox"].set_focus()
    window["listbox"].widget.config(fg="white", bg="black")

    while True:
        selected_recodings = [r for r in recordings if r.drop != "no"]
        good_recodings = [r for r in recordings if r.good]

        window["selectionTxt"].update(f"{len(selected_recodings)} item(s) (approx. {to_GiB(sum([r.rec_size for r in selected_recodings])):.1f} GiB) selected for drop | {len(good_recodings)} recordings good | {len(recordings)} total")

        recolor_gui(window)
        event, _ = window.read()

        if event == sg.WIN_CLOSED:
            quit()

        listbox_selected_rec = window["listbox"].get()

        # [O]pen recording using VLC
        if event == "o:32" and len(listbox_selected_rec) > 0:
            subprocess.Popen(["/usr/bin/env", "vlc", listbox_selected_rec[0].basepath + E2_VIDEO_EXTENSION])
            continue

        # Select for [D]rop or change reason
        if event == "d:40":
            reason_key = ask_reason()
            update_attribute(listbox_selected_rec,
                             lambda r: True,
                             lambda r: setattr(r, "drop", reason_key))
            continue

        # [K]eep from Drop
        if event == "k:45":
            update_attribute(listbox_selected_rec, lambda r: r.drop != "no", lambda r: setattr(r, "drop", "no"))
            continue

        # Mark recording as [G]ood
        if event == "g:42":
            update_attribute(listbox_selected_rec, lambda r: not r.good, lambda r: setattr(r, "good", True))
            continue

        # Mark recording as [B]ad (normal)
        if event == "b:56":
            update_attribute(listbox_selected_rec, lambda r: r.good, lambda r: setattr(r, "good", False))
            continue

        # Drop button pressed
        if event == "dropBtn":
            for_deletion = set()
            for r in [x for x in recordings if x.drop != "no"]:
                drop_recording(r)
                for_deletion.add(r)
            for r in for_deletion:
                recordings.remove(r)
            window["listbox"].update(recordings)

if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
