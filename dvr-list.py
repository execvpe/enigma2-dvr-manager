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
        self.description = remove_prefix(meta[2].strip(), self.title).strip()
        self.timestamp   = basepath.split(" ")[1]
        self.hd          = "hd" in self.channel.lower()
        self.sortkey     = alphanumeric(meta[1] + self.timestamp).lower()

    def __repr__(self) -> str:
        return f"{self.timestamp[:2]}:{self.timestamp[2:]} | {self.channel[:8].ljust(8)} | {self.title[:43].ljust(43)} | {self.description}"

def alphanumeric(line: str) -> str:
    return re.sub("[^A-Za-z0-9]+", "", line)

def format_length(raw: int) -> str:
    hours   = raw // 3_600
    raw -= hours * 3_600
    minutes = raw // 60
    raw -= minutes * 60
    seconds = raw
    return f"{hours}:{minutes:02d}:{seconds:02d}"

def remove_prefix(line: str, prefix: str) -> str:
    return re.sub(r'^{0}'.format(re.escape(prefix)), '', line)

def drop_recording(rec: Recording) -> None:
    for e in E2_EXTENSIONS:
        filepath = rec.basepath + e
        print(f"Move: {filepath}")

def main(argc: int, argv: list[str]) -> None:
    if argc < 2:
        raise IndexError(f"Usage: {argv[0]} <dir path> [dir path ...]")

    print("Reading directories...")
    filenames = []
    for d in argv[1:]:
        filenames += glob.glob(d + "/*" + E2_VIDEO_EXTENSION)
    print("Reading meta files...")
    for f in filenames:
        with open(f + ".meta") as m:
            recordings.append(Recording(re.sub("\.ts$", "", f), m.readlines()))

    print(f"Successfully read {len(filenames)} meta files.")
    print("Sorting...")
    recordings.sort(key=lambda r: r.sortkey)
    print("Finished sorting.")

    sg.ChangeLookAndFeel("Dark Black")

    gui_layout = [[sg.Text("Please select an item...", key="selectionText",
                          font=("JetBrains Mono", 14)),
                   sg.Button("Select", key="selectBtn"),
                   sg.Button("Unselect", key="unselectBtn"),
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

    window['listbox'].widget.config(bg="black", fg="white")
#   window.Maximize()

    selected_for_drop = set()
    listbox_selected_rec = []
    listbox_selected_idx = []
    while True:
        event, _ = window.read()

        if event == sg.WIN_CLOSED:
            quit()

        listbox_selected_rec = window["listbox"].get()
        listbox_selected_idx = window["listbox"].get_indexes()

        if event in ("selectBtn", "listbox") and len(listbox_selected_rec) > 0:
            for i, r in enumerate(listbox_selected_rec):
                window["listbox"].widget.itemconfig(listbox_selected_idx[i], fg='black', bg='red')
                selected_for_drop.add(r)

        if event == "unselectBtn" and len(listbox_selected_rec) > 0:
            for i, r in enumerate(listbox_selected_rec):
                window["listbox"].widget.itemconfig(listbox_selected_idx[i], fg='white', bg='black')
                selected_for_drop.remove(r)

        if event == "dropBtn" and len(listbox_selected_rec) > 0:
            drop_recording(r) #TODO
            recordings.remove(r)
            window["listbox"].update(recordings)

        window["selectionText"].update(str(len(selected_for_drop)) + " item(s) selected")



if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
