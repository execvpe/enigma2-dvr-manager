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

recordings = []

class Recording:
    def __init__(self, basepath: str, meta: str):
        self.basepath    = basepath.strip()
        self.channel     = meta[0].split(":")[-1].strip()
        self.title       = meta[1].strip()

        if len(self.title) == 0:
            self.title = "[?] " + self.basepath.split(" - ")[2]

        self.description = remove_prefix(meta[2].strip(), self.title).strip()
        self.timestamp   = os.path.basename(self.basepath).split(" ")[1]
        self.hd          = "hd" in self.channel.lower()
        self.sortkey     = alphanumeric(self.title + self.timestamp).lower()
        self.rec_size    = os.stat(basepath + E2_VIDEO_EXTENSION).st_size

        dupmeta = load_dupmeta(self)

        self.drop        = dupmeta.get("drop",     "False") == "True"
        self.good        = dupmeta.get("good",     "False") == "True"
        self.mastered    = dupmeta.get("mastered", "False") == "True"

        self.duration    = int(dupmeta.get("duration", "-2"))

        if self.duration == -2:
            self.duration = get_video_duration(self)
            save_dupmeta(self)

    def __getattributes(self) -> str:
        return f"{'D' if self.drop else ' '}{'G' if self.good else ' '}{'M' if self.mastered else ' '}"

    def __repr__(self) -> str:
        return f"{self.__getattributes()} | {self.timestamp[:2]}:{self.timestamp[2:]} | {(to_GiB(self.rec_size)):4.1f} GiB | {(self.duration // 60):3d} min | {self.channel[:10].ljust(10)} | {self.title[:42].ljust(42)} | {self.description}"

# Remove everything that is not a letter or digit
def alphanumeric(line: str) -> str:
    return re.sub("[^A-Za-z0-9]+", "", line)

def remove_prefix(line: str, prefix: str) -> str:
    return re.sub(r'^{0}'.format(re.escape(prefix)), '', line)

def to_GiB(size: int) -> float:
    return size / 1_073_741_824

def drop_recording(rec: Recording) -> None:
    for e in E2_EXTENSIONS + [DUP_META_EXTENSION]:
        filepath = rec.basepath + e
        print(filepath)

def load_dupmeta(rec: Recording) -> dict[str, str]:
    if not os.path.exists(rec.basepath + DUP_META_EXTENSION):
        return dict()
    with open(rec.basepath + DUP_META_EXTENSION, "r", encoding="utf-8") as f:
        return dict([x.strip().split("=") for x in f.readlines()])

def save_dupmeta(rec: Recording) -> None:
    with open(rec.basepath + DUP_META_EXTENSION, "w", encoding="utf-8") as f:
        f.write(f"duration={rec.duration}\ngood={rec.good}\ndrop={rec.drop}\nmastered={rec.mastered}\n")

def get_video_duration(rec: Recording) -> int:
    vid     = cv2.VideoCapture(rec.basepath + E2_VIDEO_EXTENSION)
    fps     = int(vid.get(cv2.CAP_PROP_FPS))
    frames  = int(vid.get(cv2.CAP_PROP_FRAME_COUNT))
    vid.release()

    if fps == 0:
        return -1
    return frames // fps

def recolor_gui(window: sg.Window) -> None:
    for i, r in enumerate(recordings):
        if r.drop:
            window["listbox"].widget.itemconfig(i, fg="black", bg="red")
            continue

        if r.mastered:
            window["listbox"].widget.itemconfig(i, fg="white", bg="blue")
            continue

        if r.good:
            window["listbox"].widget.itemconfig(i, fg="black", bg="light green")
            continue

        window["listbox"].widget.itemconfig(i, fg="white", bg="black")

def init_gui() -> sg.Window:
    sg.ChangeLookAndFeel("Dark Black")

    gui_layout = [[sg.Text("Please select an item...", key="selectionTxt",
                          font=("JetBrains Mono", 14)),
                   sg.Push(), sg.Button("Drop", key="dropBtn")],
                  [sg.Text("[D]rop, [K]eep | [O]pen in VLC | Mark as [G]ood, [B]ad (normal)",
                           font=("JetBrains Mono", 14), text_color="grey")],
                  [sg.Listbox(key="listbox",
                              values=recordings,
                              size=(1280, 720),
                              enable_events=True,
                              font=("JetBrains Mono", 14),
                              select_mode=sg.LISTBOX_SELECT_MODE_EXTENDED)]]

    return sg.Window(title="DVR Duplicates",
                     layout=gui_layout,
                     size=(1280, 720),
                     return_keyboard_events=True,
                     resizable=True,
                     finalize=True)

def main(argc: int, argv: list[str]) -> None:
    if argc < 2:
        raise IndexError(f"Usage: {argv[0]} <dir path> [dir path ...]")

    print("Scanning directories...", file=sys.stderr)
    filenames = []
    for d in argv[1:]:
        path = d + "/*" + E2_VIDEO_EXTENSION
        print(f"Scanning directory: {path}", end="\r", file=sys.stderr)
        filenames += glob.glob(path)
    print(f"Successfully scanned {argc - 1} directories.", file=sys.stderr)

    print("Reading meta files... (This may take a while)", file=sys.stderr)
    for i, f in enumerate(filenames):
        with open(f + ".meta", "r", encoding="utf-8") as m:
            print(f"Scanning meta file {i} of {len(filenames)}", end="\r", file=sys.stderr)
            recordings.append(Recording(re.sub("\.ts$", "", f), m.readlines()))
    print(f"Successfully read {len(filenames)} meta files.", file=sys.stderr)

    print("Sorting...", file=sys.stderr)
    recordings.sort(key=lambda r: r.sortkey)
    print("Finished sorting.", file=sys.stderr)

    window = init_gui()
    window["listbox"].widget.config(fg="white", bg="black")

    listbox_selected_rec = []
    while True:
        recolor_gui(window)
        event, _ = window.read()
        print(event, file=sys.stderr)

        if event == sg.WIN_CLOSED:
            quit()

        listbox_selected_rec = window["listbox"].get()

        # Select for [D]rop
        if event == "d:40" and len(listbox_selected_rec) > 0:
            for i, r in enumerate(listbox_selected_rec):
                r.drop = True
                save_dupmeta(r)

        # [K]eep from Drop
        if event == "k:45" and len(listbox_selected_rec) > 0:
            for i, r in enumerate(listbox_selected_rec):
                r.drop = False
                save_dupmeta(r)

        # [O]pen recording using VLC
        if event == "o:32" and len(listbox_selected_rec) > 0:
            subprocess.Popen(["/usr/bin/env", "vlc", listbox_selected_rec[0].basepath + E2_VIDEO_EXTENSION])

        # Mark recording as [G]ood
        if event == "g:42" and len(listbox_selected_rec) > 0:
            for i, r in enumerate(listbox_selected_rec):
                r.drop = False
                r.good = True
                save_dupmeta(r)

        # Mark recording as [B]ad (normal)
        if event == "b:56" and len(listbox_selected_rec) > 0:
            for i, r in enumerate(listbox_selected_rec):
                r.good = False
                save_dupmeta(r)

        selected_recodings = [r for r in recordings if r.drop]

        # Drop button pressed
        if event == "dropBtn":
            for_deletion = set()
            for r in selected_recodings:
                drop_recording(r)
                for_deletion.add(r)
            for r in for_deletion:
                recordings.remove(r)
                selected_recodings.remove(r)
            window["listbox"].update(recordings)

        good_recodings = [r for r in recordings if r.good]

        window["selectionTxt"].update(f"{len(selected_recodings)} item(s) (approx. {to_GiB(sum([r.rec_size for r in selected_recodings])):.1f} GiB) selected for drop | {len(good_recodings)} recordings good | {len(recordings)} total")

if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
