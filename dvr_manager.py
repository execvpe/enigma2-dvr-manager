#!/usr/bin/env python3

import os
import re
import sqlite3
import string
import subprocess
import sys

from datetime import datetime, timedelta
from enum     import Enum

from collections.abc import Callable
from typing import Iterator, Optional

import cv2
import FreeSimpleGUI as sg

# Enigma 2 video file extension (default: ".ts")
E2_VIDEO_EXTENSION = ".ts"
# Enigma 2 meta file extension (default: ".ts.meta")
E2_META_EXTENSION = ".ts.meta"
# Enigma 2 eit file extension (default: ".eit")
E2_EIT_EXTENSION = ".eit"
# As far as I know there are six files associated to each recording
E2_EXTENSIONS = [".eit", ".ts", ".ts.ap", ".ts.cuts", ".ts.meta", ".ts.sc"]

# A file to which the dropped file paths are appended
DROPPED_FILE = "dropped"

# The default GUI font
GUI_FONT = ("JetBrains Mono", 14)

# Add some more translations if desired
GROUPKEY_TRANSLATIONS = str.maketrans({
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss"
})


class QueryType(Enum):
    ATTRIBUTE = 0
    AGGREGATE = 1

class SortOrder(Enum):
    ASC = 0
    DESC = 1

    def __str__(self) -> str:
        return super().__str__().strip(f"{self.__class__.__name__}.")

class Entry:
    pass

class Recording(Entry):
    basepath: Optional[str]
    file_basename: str
    file_size: int
    epg_channel: str
    epg_title: str
    epg_description: str
    video_duration: int
    video_height: int
    video_width: int
    video_fps: int
    is_good: bool
    is_dropped: bool
    is_mastered: bool
    groupkey: str
    sortkey: int
    comment: str
    timestamp: str

    def hd(self) -> bool:
        return self.video_height >= 720

    def __attributes(self) -> str:
        return f"{'D' if self.is_dropped else '.'}{'G' if self.is_good else '.'}{'M' if self.is_mastered else '.'}{'C' if len(self.comment) > 0 else '.'}"

    def __endtime(self) -> str:
        dt = datetime.strptime(self.timestamp, "%Y-%m-%d %H:%M")
        dt += timedelta(seconds=self.video_duration)

        return datetime.strftime(dt, "%H:%M")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Recording):
            return False
        return self.file_basename == other.file_basename

    def __hash__(self) -> int:
        return self.file_basename.__hash__()

    def __repr__(self) -> str:
        return f"{self.__attributes()} | {self.timestamp} - {self.__endtime()} | {(to_GiB(self.file_size)):4.1f} GiB | {(self.video_duration // 60):3d}' | {fit_string(self.epg_channel, 10, 2).ljust(10)} | {fit_string(self.epg_title, 45, 7).ljust(45)} | {self.epg_description}"

class Download(Entry):
    dl_key: str
    dl_source: str
    dl_title: str
    dl_description: str
    video_duration: int
    video_height: int
    video_width: int
    video_fps: int
    groupkey: str
    sortkey: int
    comment: str
    timestamp: str

    def hd(self) -> bool:
        return self.video_height >= 720

    def __attributes(self) -> str:
        return f"   {'C' if len(self.comment) > 0 else '.'}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Download):
            return False
        return self.dl_key == other.dl_key

    def __hash__(self) -> int:
        return self.dl_key.__hash__()

    def __repr__(self) -> str:
        return f"{self.__attributes()} | {self.timestamp} | {(to_GiB(self.file_size)):4.1f} GiB | {(self.video_duration // 60):3d}' | {fit_string(self.dl_source, 10, 2).ljust(10)} | {fit_string(self.dl_title, 45, 7).ljust(45)} | {self.dl_description}"

# Global entry list
global_entrylist: list[Entry] = []
# FreeSimpleGUI window object
window: sg.Window
# Recording cache database
database = sqlite3.connect("database.sqlite3")

class RecordingFactory:
    @staticmethod
    def from_meta_file(basepath: str, meta: list[str]) -> Recording:
        rec = Recording()

        rec.basepath = basepath

        rec.file_basename, rec.file_size = os.path.basename(basepath), os.stat(basepath + E2_VIDEO_EXTENSION).st_size
        rec.epg_channel, rec.epg_title = meta[0].split(":")[-1].strip(), meta[1].strip()
        rec.epg_description = remove_prefix(meta[2].strip(), rec.epg_title).strip()
        rec.video_duration, rec.video_height, rec.video_width, rec.video_fps = get_video_metadata(rec)
        rec.is_good, rec.is_dropped, rec.is_mastered = False, False, False
        rec.comment = ""

        basename_tokens = rec.file_basename.split(" - ")

        rec.timestamp = datetime.strftime(
            datetime.strptime(basename_tokens[0], "%Y%m%d %H%M"),
            "%Y-%m-%d %H:%M")

        if len(rec.epg_channel) == 0:
            rec.epg_channel = basename_tokens[1]
        if len(rec.epg_title) == 0:
            rec.epg_title = basename_tokens[2]

        rec.groupkey  = make_groupkey(rec.epg_title)

        return rec

    @staticmethod
    def from_database(basepath: str) -> Optional[Recording]:
        basename = os.path.basename(basepath)

        if (rec := db_load_rec(basename)) is None:
            return None

        assert rec.file_size == os.stat(basepath + E2_VIDEO_EXTENSION).st_size, str(rec)

        rec.basepath = basepath

        return rec

    @staticmethod
    def from_database_mastered_all() -> list[Recording]:
        if (all_mastered := db_load_rec_mastered_all()) is None:
            return []

        for r in all_mastered:
            r.basepath = None
            r.file_size = 0

        return all_mastered

class DownloadFactory:
    @staticmethod
    def from_database_all() -> list[Download]:
        if (all_downloads := db_load_dl_all()) is None:
            return []
        return all_downloads

# Remove everything that is not a letter or digit
def make_groupkey(line: str) -> str:
    return re.sub(r"[^a-z0-9]+", "",
                  line.lower()
                      .translate(GROUPKEY_TRANSLATIONS))

def fit_string(line: str, length: int, end: int) -> str:
    if len(line) <= length:
        return line
    return f"{line[:(length - end - 1)]}*{line[-end:]}"

def remove_prefix(line: str, prefix: str) -> str:
    return re.sub(rf"^{re.escape(prefix)}", "~", line)

def to_GiB(size: int) -> float:
    return size / 1_073_741_824

def drop_recording(rec: Recording) -> None:
    assert isinstance(rec, Recording)
    with open(DROPPED_FILE, "a", encoding="utf-8") as f:
        for e in E2_EXTENSIONS:
            assert rec.basepath is not None
            filepath = rec.basepath + e
            if os.path.exists(filepath):
                print(filepath, file=f)
    db_remove(rec)

def sort_global_entrylist(order_by: str, query_type: QueryType, sort_order: SortOrder) -> None:
    key_ranks = db_rank(order_by, query_type, sort_order)
    if query_type == QueryType.ATTRIBUTE:
        for r in global_entrylist:
            r.sortkey = key_ranks.get(r.file_basename, 0)
    if query_type == QueryType.AGGREGATE:
        for r in global_entrylist:
            r.sortkey = key_ranks.get(r.groupkey, 0)
    global_entrylist.sort(key=lambda r: r.sortkey)

def update_attribute(recs: list[Recording],
                     check: Callable[[Recording], bool],
                     update: Callable[[Recording], None]) -> None:
    if len(recs) == 0:
        return
    for r in recs:
        assert isinstance(r, Recording)
        if check(r):
            update(r)
            db_save(r)
            i = global_entrylist.index(r)
            window["recordingBox"].widget.delete(i)
            window["recordingBox"].widget.insert(i, r)
    gui_reselect(recs)

def get_video_metadata(rec: Recording) -> tuple[int, int, int, int]:
    assert isinstance(rec, Recording)
    assert rec.basepath is not None
    vid = cv2.VideoCapture(rec.basepath + E2_VIDEO_EXTENSION)

    fps    = int(vid.get(cv2.CAP_PROP_FPS))
    frames = int(vid.get(cv2.CAP_PROP_FRAME_COUNT))
    height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
    width  = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))

    vid.release()

    duration = frames // fps if fps != 0 else -1

    return (duration, height, width, fps)

def get_eit_data(rec: Recording) -> str:
    assert isinstance(rec, Recording)
    assert rec.basepath is not None
    with open(rec.basepath + E2_EIT_EXTENSION, "rb") as f:
        # Filter out non-printable charactes / header information
        content = bytes(c if c in range(ord(' '), ord('~')) else ord('.') for c in f.read())
        # Convert to string
        return content.decode("ascii")

def gui_init() -> None:
    sg.change_look_and_feel("Dark Black")

    gui_layout = [[sg.Column([[sg.Text(key="informationTxt",
                               font=GUI_FONT)],
                              [sg.HorizontalSeparator(color="green")],
                              [sg.Text("[F]ind | [I]nformation | [O]pen in VLC | [C]omment | [D]rop | [G]ood | [M]astered | Undo: [Shift + 'Key']",
                               font=GUI_FONT, text_color="grey")],
                              [sg.HorizontalSeparator(color="green")],
                              [sg.Text("Order by", font=GUI_FONT, text_color="grey"), sg.Column([
                              [sg.Radio("Title", "sortRadio", font=GUI_FONT, enable_events=True, default=True, metadata=("groupkey", QueryType.ATTRIBUTE)),
                               sg.Radio("Channel", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("epg_channel", QueryType.ATTRIBUTE)),
                               sg.Radio("Date", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("timestamp", QueryType.ATTRIBUTE)),
                               sg.Radio("Time", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("TIME(timestamp)", QueryType.ATTRIBUTE)),
                               sg.Radio("Size", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("file_size", QueryType.ATTRIBUTE)),
                               sg.Radio("Duration", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("video_duration", QueryType.ATTRIBUTE)),
                               sg.Radio("drop", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("is_dropped", QueryType.ATTRIBUTE)),
                               sg.Radio("good", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("is_good", QueryType.ATTRIBUTE)),
                               sg.Radio("mastered", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("is_mastered", QueryType.ATTRIBUTE)),
                               sg.Radio("COUNT", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("COUNT(*)", QueryType.AGGREGATE)),],
                              [sg.Radio("AVG(size)", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("AVG(file_size)", QueryType.AGGREGATE)),
                               sg.Radio("MAX(size)", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("MAX(file_size)", QueryType.AGGREGATE)),
                               sg.Radio("SUM(size)", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("SUM(file_size)", QueryType.AGGREGATE)),
                               sg.Radio("ANY(drop)", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("MAX(is_dropped)", QueryType.AGGREGATE)),
                               sg.Radio("ANY(good)", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("MAX(is_good)", QueryType.AGGREGATE)),
                               sg.Radio("ANY(mastered)", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("MAX(is_mastered)", QueryType.AGGREGATE)),
                               sg.Radio("Resolution", "sortRadio", font=GUI_FONT, enable_events=True, metadata=("video_height", QueryType.ATTRIBUTE)),]]),
                               sg.Push(), sg.VerticalSeparator(color="green"), sg.Column([
                              [sg.Radio("ASC", "orderRadio", font=GUI_FONT, enable_events=True, default=True, metadata=SortOrder.ASC)],
                              [sg.Radio("DESC", "orderRadio", font=GUI_FONT, enable_events=True, metadata=SortOrder.DESC)]])],
                              [sg.HorizontalSeparator(color="green")],
                              [sg.Text("SELECT Mode", key="metaTxt", font=GUI_FONT, text_color="yellow"),
                               sg.VerticalSeparator(color="green"),
                               sg.Text(key="selectionTxt", font=GUI_FONT, text_color="yellow"),
                               sg.Push(),
                               sg.Input(key="findInput",
                                            size=40,
                                            font=GUI_FONT,
                                            do_not_clear=False,
                                            disabled=True),
                               sg.VerticalSeparator(color="green"),
                               sg.Button("Drop", key="dropBtn")],]),
                   sg.Push(),
                   sg.Multiline(key="commentMul",
                                size=(80, 6),
                                font=GUI_FONT,
                                disabled=True)],
                  [sg.Listbox(key="recordingBox",
                              values=global_entrylist,
                              size=(1280, 720),
                              enable_events=True,
                              font=GUI_FONT,
                              select_mode=sg.LISTBOX_SELECT_MODE_EXTENDED)]]

    global window
    window = sg.Window(title="DVR Duplicate Removal Tool",
                       layout=gui_layout,
                       return_keyboard_events=True,
                       resizable=True,
                       finalize=True)

    window["recordingBox"].set_focus()
    window["recordingBox"].widget.config(fg="white", bg="black")
    window["commentMul"].widget.config(fg="white", bg="black")
    window["findInput"].widget.config(fg="white", bg="black")

def gui_find(find_string: str) -> int:
    matches = []
    for i, r in enumerate(global_entrylist):
        if r.groupkey.startswith(make_groupkey(find_string)):
            matches.append(i)

    if len(matches) > 0:
        window["recordingBox"].widget.see(matches[0])

    return len(matches)

def gui_recolor(window: sg.Window) -> None:
    for i, r in enumerate(global_entrylist):
        assert isinstance(r, Recording)
        if r.is_dropped:
            window["recordingBox"].widget.itemconfig(i, fg="white", bg="red")
            continue

        if r.is_mastered:
            window["recordingBox"].widget.itemconfig(i, fg="white", bg="blue")
            continue

        if not r.hd():
            window["recordingBox"].widget.itemconfig(i, fg="grey", bg="black")
            continue

        if r.is_good:
            window["recordingBox"].widget.itemconfig(i, fg="black", bg="light green")
            continue

        window["recordingBox"].widget.itemconfig(i, fg="white", bg="black")

def gui_reselect(recs: list[Recording]) -> None:
    jump_indices = [i for i, r in enumerate(global_entrylist) if r in recs]
    for i in jump_indices:
        window["recordingBox"].widget.selection_set(i)
    window["recordingBox"].widget.see(jump_indices[0])

def db_init() -> None:
    c = database.cursor()
    c.execute("""
              CREATE TABLE IF NOT EXISTS
                recordings(file_basename VARCHAR PRIMARY KEY,
                  groupkey VARCHAR, timestamp DATETIME, file_size INT,
                  epg_channel VARCHAR, epg_title VARCHAR, epg_description VARCHAR,
                  video_duration INT, video_height INT, video_width INT, video_fps INT,
                  is_good BOOL, is_dropped BOOL, is_mastered BOOL, comment VARCHAR);
              """)

    c.execute("""
              CREATE TABLE IF NOT EXISTS
                downloads(dl_key VARCHAR PRIMARY KEY,
                  groupkey VARCHAR, timestamp DATETIME,
                  dl_source VARCHAR, dl_title VARCHAR, dl_description VARCHAR,
                  video_duration INT, video_height INT, video_width INT, video_fps INT,
                  comment VARCHAR);
              """)

def db_load_rec(basename: str) -> Optional[Recording]:
    c = database.cursor()
    c.execute("""
              SELECT file_basename, file_size,
                epg_channel, epg_title, epg_description,
                video_duration, video_height, video_width, video_fps,
                is_good, is_dropped, is_mastered, groupkey, comment, timestamp
              FROM recordings
              WHERE file_basename = ?;
              """, (basename, ))

    if (raw := c.fetchone()) is None:
        return None

    rec = Recording()
    rec.file_basename, rec.file_size = raw[0], int(raw[1])
    rec.epg_channel, rec.epg_title, rec.epg_description = raw[2], raw[3], raw[4]
    rec.video_duration, rec.video_height, rec.video_width, rec.video_fps = raw[5], raw[6], raw[7], raw[8]
    rec.is_good, rec.is_dropped, rec.is_mastered = bool(raw[9]), raw[10], bool(raw[11])
    rec.groupkey, rec.comment = raw[12], raw[13]
    rec.timestamp = raw[14]

    return rec

def db_load_dl_all(basename: str) -> Optional[list[Download]]:
    c = database.cursor()
    c.execute("""
              SELECT dl_key,
                dl_source, dl_title, dl_description,
                video_duration, video_height, video_width, video_fps,
                groupkey, comment, timestamp
              FROM downloads;
              """)

    if len(all_raw := c.fetchall()) == 0:
        return None

    all_downloads = []
    for raw in all_raw:
        dl = Download()
        dl.dl_key = raw[0]
        dl.dl_source, dl.dl_title, dl.dl_description = raw[1], raw[2], raw[3]
        dl.video_duration, dl.video_height, dl.video_width, dl.video_fps = raw[4], raw[5], raw[6], raw[7]
        dl.groupkey, dl.comment, dl.timestamp = raw[8], raw[9], raw[10]

        all_downloads.append(dl)

    return all_downloads

def db_load_rec_mastered_all() -> Optional[list[Recording]]:
    c = database.cursor()
    c.execute("""
              SELECT file_basename, file_size,
                epg_channel, epg_title, epg_description,
                video_duration, video_height, video_width, video_fps,
                is_good, is_dropped, is_mastered, groupkey, comment, timestamp
              FROM recordings
              WHERE is_mastered = TRUE;
              """)

    if len(all_raw := c.fetchall()) == 0:
        return None

    all_mastered = []
    for raw in all_raw:
        rec = Recording()
        rec.file_basename, rec.file_size = raw[0], int(raw[1])
        rec.epg_channel, rec.epg_title, rec.epg_description = raw[2], raw[3], raw[4]
        rec.video_duration, rec.video_height, rec.video_width, rec.video_fps = raw[5], raw[6], raw[7], raw[8]
        rec.is_good, rec.is_dropped, rec.is_mastered = bool(raw[9]), raw[10], bool(raw[11])
        rec.groupkey, rec.comment = raw[12], raw[13]
        rec.timestamp = raw[14]

        all_mastered.append(rec)

    return all_mastered

def db_rank(order_by: str, query_type: QueryType, sort_order: SortOrder) -> dict[str, int]:
    # Yes, the following database calls are vulnerable to SQL injections,
    # but the tuple solution does not work here.
    # Please let me know if you have a better solution...

    c = database.cursor()
    if query_type == QueryType.ATTRIBUTE:
        c.execute(f"""
                  SELECT file_basename,
                         ROW_NUMBER() OVER (ORDER BY {order_by} {sort_order}, groupkey, timestamp)
                  FROM recordings
                  ORDER BY file_basename;
                  """)
    if query_type == QueryType.AGGREGATE:
        c.execute(f"""
                  SELECT groupkey,
                         ROW_NUMBER() OVER (ORDER BY {order_by} {sort_order}, groupkey, timestamp)
                  FROM recordings
                  GROUP BY groupkey
                  ORDER BY groupkey;
                  """)

    return dict(c.fetchall())

def db_save(rec: Recording) -> None:
    assert isinstance(rec, Recording)
    db_remove(rec)
    c = database.cursor()
    c.execute("""
              INSERT INTO recordings(file_basename, file_size,
                epg_channel, epg_title, epg_description,
                video_duration, video_height, video_width, video_fps,
                is_good, is_dropped, is_mastered, groupkey,
                comment, timestamp)
              VALUES (?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?);
              """, (rec.file_basename, rec.file_size,
              rec.epg_channel, rec.epg_title, rec.epg_description,
              rec.video_duration, rec.video_height, rec.video_width, rec.video_fps,
              rec.is_good, rec.is_dropped, rec.is_mastered, rec.groupkey,
              rec.comment, rec.timestamp))

    database.commit()

def db_remove(rec: Recording) -> None:
    assert isinstance(rec, Recording)
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

def get_files_from_directory(dirs: list[str]) -> list[str]:
    print("Scanning directories... (This may take a while)", file=sys.stderr)

    files = []
    for i, d in enumerate(dirs):
        print(f"Scanning directory: {i + 1} of {len(dirs)}", end="\r", file=sys.stderr)
        files += all_recordings_in(d)

    print(f"Successfully scanned {len(dirs)} directories.", file=sys.stderr)

    return files

def process_recordings(files: list[str]) -> None:
    print("Processing recordings... (This may take a while)", file=sys.stderr)

    db_count = 0
    for i, f in enumerate(files):
        print(f"Processing recording {i + 1} of {len(files)}", end="\r", file=sys.stderr)
        basepath = re.sub(rf"\{E2_VIDEO_EXTENSION}$", "", f)
        if (rec := RecordingFactory.from_database(basepath)) is not None:
            global_entrylist.append(rec)
            db_count += 1
            continue
        try:
            with open(basepath + E2_META_EXTENSION, "r", encoding="utf-8") as m:
                rec = RecordingFactory.from_meta_file(basepath, m.readlines())
                db_save(rec)
                global_entrylist.append(rec)
        except FileNotFoundError:
            print(f"{f}.meta not found! Skipping...", file=sys.stderr)

    # Always load mastered recordings from database, even if they are deleted
    deleted = [rec for rec in RecordingFactory.from_database_mastered_all() if rec not in global_entrylist]
    global_entrylist.extend(deleted)

    print(f"Recordings successfully processed: {len(global_entrylist)} total entries | {len(files)} files ({db_count} in cache, {len(files) - db_count} new) and {len(deleted)} deleted after mastering", file=sys.stderr)

def main(argc: int, argv: list[str]) -> None:
    if argc < 2:
        raise IndexError(f"Usage: {argv[0]} <dir path> [dir path ...]")

    db_init()

    # Crawl directory tree for recordings, search cache, add them to the list
    process_recordings(get_files_from_directory(argv[1:]))

    radios_metadata = (("groupkey", QueryType.ATTRIBUTE), SortOrder.ASC)
    sort_global_entrylist(radios_metadata[0][0], radios_metadata[0][1], radios_metadata[1])
    radios_metadata_previous = radios_metadata

    gui_init()

    while True:
        selected_recodings = [r for r in global_entrylist if r.is_dropped]
        good_recodings = [r for r in global_entrylist if r.is_good]
        mastered_recodings = [r for r in global_entrylist if r.is_mastered]

        radios_metadata = tuple(r.metadata for r in window.element_list() if isinstance(r, sg.Radio) and r.get())
        if isinstance(radios_metadata[0], SortOrder):
            radios_metadata = radios_metadata[::-1]

        if radios_metadata != radios_metadata_previous:
            recordingBox_selected_rec = window["recordingBox"].get()
            sort_global_entrylist(radios_metadata[0][0], radios_metadata[0][1], radios_metadata[1])
            window["recordingBox"].update(global_entrylist)
            if len(recordingBox_selected_rec) > 0:
                gui_reselect(recordingBox_selected_rec)
            radios_metadata_previous = radios_metadata


        window["informationTxt"].update(f"{len(selected_recodings)} entries (approx. {to_GiB(sum(r.file_size for r in selected_recodings)):.1f} GiB) selected for drop | {len(good_recodings)} good | {len(mastered_recodings)} mastered | {len(global_entrylist)} total")

        gui_recolor(window)
        event, _ = window.read()

        if event == sg.WIN_CLOSED:
            sys.exit()

        recordingBox_selected_rec = window["recordingBox"].get()

        if len(recordingBox_selected_rec) > 0:
            r = recordingBox_selected_rec[0]
            window["metaTxt"].update(f"{r.video_width:4d}x{r.video_height:4d} @ {r.video_fps} fps")
            window["selectionTxt"].update(f"{len(recordingBox_selected_rec)} entries under cursor")
            window["commentMul"].update(recordingBox_selected_rec[0].comment)

        # [C]omment
        if ((event == "c:54" and len(recordingBox_selected_rec) == 1)
        or ( event == "C:54" and len(recordingBox_selected_rec) >  0)):
            window["recordingBox"].update(disabled=True)
            window["dropBtn"].update(disabled=True)
            window["metaTxt"].update("COMMENT Mode | Submit: [ESC]")
            window["commentMul"].update(disabled=False)
            window["commentMul"].set_focus()

            while True:
                event, _ = window.read()

                if event == sg.WIN_CLOSED:
                    sys.exit()

                if event != "Escape:9":
                    continue

                comment = window["commentMul"].get()
                break

            window["commentMul"].update(disabled=True)
            window["dropBtn"].update(disabled=False)
            window["metaTxt"].update("SELECT Mode")
            window["recordingBox"].update(disabled=False)
            update_attribute(recordingBox_selected_rec,
                             lambda r: True,
                             lambda r: setattr(r, "comment", comment))
            window["recordingBox"].set_focus()
            continue

        # [F]ind
        if event == "f:41":
            window["recordingBox"].update(disabled=True)
            window["dropBtn"].update(disabled=True)
            window["metaTxt"].update("FIND Mode | Submit: [ESC]")
            window["findInput"].update("", disabled=False)
            window["findInput"].set_focus()

            while True:
                event, _ = window.read()

                if event == sg.WIN_CLOSED:
                    sys.exit()

                matches_found = gui_find(window["findInput"].get())
                window["selectionTxt"].update(f"{matches_found} matching entries found")

                if event == "Escape:9":
                    break

            window["findInput"].update(disabled=True)
            window["dropBtn"].update(disabled=False)
            window["metaTxt"].update("SELECT Mode")
            window["recordingBox"].update(disabled=False)
            window["recordingBox"].set_focus()
            continue

        # [I]nformation from EIT entry
        if event == "i:31" and len(recordingBox_selected_rec) == 1:
            sg.popup(get_eit_data(recordingBox_selected_rec[0]),
                     title=f"EIT - {recordingBox_selected_rec[0].epg_title}",
                     font=GUI_FONT,
                     any_key_closes=True,
                     location=window.current_location())
            continue

        # [O]pen recording using VLC
        if event == "o:32" and len(recordingBox_selected_rec) > 0:
            if (bp := recordingBox_selected_rec[0].basepath) is not None:
                subprocess.Popen(["/usr/bin/env", "vlc", bp + E2_VIDEO_EXTENSION])
            continue

        # Select for [D]rop
        if event == "d:40":
            update_attribute(recordingBox_selected_rec,
                             lambda r: not r.is_mastered,
                             lambda r: setattr(r, "is_dropped", True))
            continue

        if event == "D:40":
            update_attribute(recordingBox_selected_rec,
                             lambda r: r.is_dropped ,
                             lambda r: setattr(r, "is_dropped", False))
            continue

        # Mark recording as [G]ood
        if event == "g:42":
            update_attribute(recordingBox_selected_rec,
                             lambda r: not r.is_good,
                             lambda r: setattr(r, "is_good", True))
            continue

        if event == "G:42":
            update_attribute(recordingBox_selected_rec,
                             lambda r: r.is_good,
                             lambda r: setattr(r, "is_good", False))
            continue

        # Mark recording as [M]astered
        if event == "m:58":
            update_attribute(recordingBox_selected_rec,
                             lambda r: not r.is_dropped,
                             lambda r: setattr(r, "is_mastered", True))
            continue

        if event == "M:58":
            update_attribute(recordingBox_selected_rec,
                             lambda r: r.is_mastered,
                             lambda r: setattr(r, "is_mastered", False))
            continue

        # Drop button pressed
        if event == "dropBtn":
            for_deletion = set()
            for r in [x for x in global_entrylist if x.is_dropped]:
                drop_recording(r)
                for_deletion.add(r)
            for r in for_deletion:
                global_entrylist.remove(r)
            window["recordingBox"].update(global_entrylist)

if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
