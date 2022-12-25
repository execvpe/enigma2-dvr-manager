#!/usr/bin/env python3

import glob
import PySimpleGUI as sg
import os
import re
import sys

E2_VIDEO_EXTENSION = ".ts"
E2_EXTENSIONS = [".eit", ".ts", ".ts.ap", ".ts.cuts", ".ts.meta", ".ts.sc"]

recordings = []

class Recording:
    def __init__(self, basepath: str, meta: str):
        self.basepath    = basepath.strip()
        self.channel     = meta[0].split(":")[-1].strip()
        self.title       = meta[1].strip()

        if len(self.title) == 0:
            self.title = "[?] " + self.basepath.split(" - ")[2]

        self.description = remove_prefix(meta[2].strip(), self.title).strip()
        self.timestamp   = self.basepath.split(" ")[1]
        self.hd          = "hd" in self.channel.lower()
        self.sortkey     = alphanumeric(self.title + self.timestamp).lower()
        self.rec_size    = os.stat(basepath + E2_VIDEO_EXTENSION).st_size
        self.selected    = False


    def __repr__(self) -> str:
        return f"{self.timestamp[:2]}:{self.timestamp[2:]} | {(self.rec_size // 1_073_741_824):2d}GB | {self.channel[:10].ljust(10)} | {self.title[:42].ljust(42)} | {self.description}"

def alphanumeric(line: str) -> str:
    return re.sub("[^A-Za-z0-9]+", "", line)

def remove_prefix(line: str, prefix: str) -> str:
    return re.sub(r'^{0}'.format(re.escape(prefix)), '', line)

def drop_recording(rec: Recording) -> None:
    for e in E2_EXTENSIONS:
        filepath = rec.basepath + e
        print(filepath)

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
        with open(f + ".meta") as m:
            print(f"Scanning meta file {i} of {len(filenames)}", end="\r", file=sys.stderr)
            recordings.append(Recording(re.sub("\.ts$", "", f), m.readlines()))
    print(f"Successfully read {len(filenames)} meta files.", file=sys.stderr)

    print("Sorting...", file=sys.stderr)
    recordings.sort(key=lambda r: r.sortkey)
    print("Finished sorting.", file=sys.stderr)

    sg.ChangeLookAndFeel("Dark Black")

    gui_layout = [[sg.Text("Please select an item...", key="selectionTxt",
                          font=("JetBrains Mono", 14)),
                   sg.Button("Toggle Selection", key="selectionBtn"),
                   sg.Push(), sg.Button("Drop", key="dropBtn")],
                  [sg.Listbox(key="listbox",
                              values=recordings,
                              size=(1280, 720),
                              font=("JetBrains Mono", 14),
                              enable_events=False,
                              bind_return_key=True,
                              select_mode=sg.LISTBOX_SELECT_MODE_EXTENDED
                              )]]

    window = sg.Window(title="dvr duplicates",
                       layout=gui_layout,
                       size=(1280, 720),
                       resizable=True,
                       finalize=True)

    window['listbox'].widget.config(fg="white", bg="black")
#   window.Maximize()

    listbox_selected_rec = []
    listbox_selected_idx = []
    while True:
        event, _ = window.read()

        if event == sg.WIN_CLOSED:
            quit()

        listbox_selected_rec = window["listbox"].get()
        listbox_selected_idx = window["listbox"].get_indexes()

        if event in ("selectionBtn", "listbox") and len(listbox_selected_rec) > 0:
            for i, r in enumerate(listbox_selected_rec):
                colors = ("white", "black") if r.selected else ("black", "red")
                window["listbox"].widget.itemconfig(listbox_selected_idx[i], fg=colors[0], bg=colors[1])
                r.selected = not r.selected

        if event == "dropBtn" and len(listbox_selected_rec) > 0:
            for_deletion = set()
            for r in recordings:
                if not r.selected:
                    continue
                drop_recording(r)
                for_deletion.add(r)
            for r in for_deletion:
                recordings.remove(r)
            window["listbox"].update(recordings)

        window["selectionTxt"].update(str(len([True for r in recordings if r.selected])) + " item(s) selected")



if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
