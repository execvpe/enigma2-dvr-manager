#!/usr/bin/env python3

import json
import os
import re
import sqlite3
import string
import subprocess
import sys

from collections.abc import Callable
from datetime        import datetime, timedelta
from enum            import Enum
from typing          import Iterator, Optional

import cv2
import FreeSimpleGUI as sg

# Enigma 2 video file extension (default: ".ts")
E2_VIDEO_EXTENSION = ".ts"
# Enigma 2 meta file extension (default: ".ts.meta")
E2_META_EXTENSION  = ".ts.meta"
# Enigma 2 eit file extension (default: ".eit")
E2_EIT_EXTENSION   = ".eit"
# As far as I know there are six files associated to each recording
E2_EXTENSIONS      = [".eit", ".ts", ".ts.ap", ".ts.cuts", ".ts.meta", ".ts.sc"]

# Download file name pattern
DL_REGEX_PATTERN = re.compile(r"^(.*?) \((\d{4})\) \[(.*?=.*?)\] - (.*?)$")

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
    file_size:     int

    epg_channel:     str
    epg_title:       str
    epg_description: str

    video_duration: int
    video_height:   int
    video_width:    int
    video_fps:      int

    is_good:     bool
    is_dropped:  bool
    is_mastered: bool

    groupkey:  str
    comment:   str
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
    basepath: Optional[str]

    file_basename:  str
    file_extension: str
    file_size:      int

    dl_source:      str
    dl_title:       str
    dl_description: str

    video_duration: int
    video_height:   int
    video_width:    int
    video_fps:      int

    groupkey: str
    comment:  str

    def hd(self) -> bool:
        return self.video_height >= 720

    def __attributes(self) -> str:
        return f" GM{'C' if len(self.comment) > 0 else '.'}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Download):
            return False
        return self.file_basename == other.file_basename

    def __hash__(self) -> int:
        return self.file_basename.__hash__()

    def __repr__(self) -> str:
        return f"{self.__attributes()} | {fit_string(self.dl_source, 24, 2).ljust(24)} | {(to_GiB(self.file_size)):4.1f} GiB | {(self.video_duration // 60):3d}' |        --- | {fit_string(self.dl_title, 45, 7).ljust(45)} | {self.dl_description}"

class RecordingFactory:
    @staticmethod
    def from_meta_file(basepath: str, meta_file_extension: str) -> Recording:
        try:
            with open(basepath + meta_file_extension, "r", encoding="utf-8") as m:
                meta = m.readlines()
        except FileNotFoundError:
            print(f"Meta file for {basepath} not found! Skipping...", file=sys.stderr)
            return None

        rec = Recording()

        rec.basepath = basepath

        rec.file_basename = os.path.basename(basepath)
        rec.file_size     = os.stat(basepath + E2_VIDEO_EXTENSION).st_size

        rec.epg_channel     = meta[0].split(":")[-1].strip()
        rec.epg_title       = meta[1].strip()
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

        rec.groupkey = make_groupkey(rec.epg_title)

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
    def from_video_file(basepath: str, video_file_extension: str) -> Download:
        dl = Download()

        dl.basepath = basepath

        dl.file_basename  = os.path.basename(basepath)
        dl.file_extension = video_file_extension

        assert (match := DL_REGEX_PATTERN.match(dl.file_basename))

        dl.file_size = os.stat(basepath + dl.file_extension).st_size

        dl.dl_source      = match.group(4)
        dl.dl_title       = match.group(1)
        dl.dl_description = f"{match.group(2)} ({match.group(3)})"

        dl.video_duration, dl.video_height, dl.video_width, dl.video_fps = get_video_metadata(dl)

        dl.comment = ""

        dl.groupkey = make_groupkey(dl.dl_title)

        return dl

    @staticmethod
    def from_database_all() -> list[Download]:
        if (all_downloads := db_load_dl_all()) is None:
            return []
        return all_downloads

# Global entry list
global_entrylist: list[Entry] = []
# FreeSimpleGUI window object
window: sg.Window
# Recording cache database
database = sqlite3.connect("database.sqlite3")

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
    db_remove_rec(rec)

def sort_global_entrylist(order_by: str, sort_order: SortOrder) -> None:
    groupkey_aggregates = {}

    for e in global_entrylist:
        meta = groupkey_aggregates.get(e.groupkey, {})

        meta["max_size"] = max(meta.get("max_size", 0),  e.file_size)
        meta["sum_size"] =     meta.get("sum_size", 0) + e.file_size
        meta["count"]    =     meta.get("count",    0) + 1

        if isinstance(e, Recording):
            meta["any_drop"]     = meta.get("any_drop",     False) or e.is_dropped
            meta["any_good"]     = meta.get("any_good",     False) or e.is_good
            meta["any_mastered"] = meta.get("any_mastered", False) or e.is_mastered

        groupkey_aggregates[e.groupkey] = meta

    lambdas = {
        "title":         lambda e:  e.groupkey,
        "channel":       lambda e: (e.epg_channel          if isinstance(e, Recording) else e.dl_source, e.groupkey),
        "date":          lambda e: (e.timestamp            if isinstance(e, Recording) else "",          e.groupkey),
        "time":          lambda e: (e.timestamp.split()[1] if isinstance(e, Recording) else "",          e.groupkey),
        "attr_good":     lambda e: (not (e.is_good         if isinstance(e, Recording) else True),       e.groupkey),
        "attr_mastered": lambda e: (not (e.is_mastered     if isinstance(e, Recording) else True),       e.groupkey),
        "attr_dropped":  lambda e: (not (e.is_dropped      if isinstance(e, Recording) else False),      e.groupkey),
        "duration":      lambda e: (e.video_duration,                                                    e.groupkey),
        "resolution":    lambda e: (e.video_height,                                                      e.groupkey),
        "size":          lambda e: (e.file_size,                                                         e.groupkey),

        "max_size":      lambda e: (groupkey_aggregates[e.groupkey]["max_size"],                                            e.groupkey),
        "sum_size":      lambda e: (groupkey_aggregates[e.groupkey]["sum_size"],                                            e.groupkey),
        "avg_size":      lambda e: (groupkey_aggregates[e.groupkey]["sum_size"] / groupkey_aggregates[e.groupkey]["count"], e.groupkey),
        "count":         lambda e: (groupkey_aggregates[e.groupkey]["count"],                                               e.groupkey),

        "any_drop":      lambda e: (not groupkey_aggregates[e.groupkey].get("any_drop",     False), e.groupkey),
        "any_good":      lambda e: (not groupkey_aggregates[e.groupkey].get("any_good",     False), e.groupkey),
        "any_mastered":  lambda e: (not groupkey_aggregates[e.groupkey].get("any_mastered", False), e.groupkey),
    }

    global_entrylist.sort(key=lambdas[order_by],
                          reverse=(sort_order == SortOrder.DESC))

def update_attribute(entries: list[Entry],
                     check: Callable[[Entry], bool],
                     update: Callable[[Entry], None]) -> None:
    if len(entries) == 0:
        return
    for e in entries:
        if check(e):
            update(e)

            if isinstance(e, Recording):
                db_save_rec(e)
            else:
                db_save_dl(e)

            i = global_entrylist.index(e)

            window["recordingBox"].widget.delete(i)
            window["recordingBox"].widget.insert(i, e)

    gui_reselect(entries)

def get_video_metadata(entry: Entry) -> tuple[int, int, int, int]:
    assert entry.basepath is not None

    if isinstance(entry, Recording):
        vid = cv2.VideoCapture(entry.basepath + E2_VIDEO_EXTENSION)
    else:
        vid = cv2.VideoCapture(entry.basepath + entry.file_extension)

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

    gui_layout = [[sg.Column([[sg.Text(key="informationText",
                               font=GUI_FONT)],
                              [sg.HorizontalSeparator(color="green")],
                              [sg.Text("[F]ind | [I]nformation | [O]pen in VLC | [C]omment | [D]rop | [G]ood | [M]astered | Undo: [Shift + 'Key']",
                               font=GUI_FONT, text_color="grey")],
                              [sg.HorizontalSeparator(color="green")],
                              [sg.Text("Order by", font=GUI_FONT, text_color="grey"), sg.Column([
                              [sg.Radio("Title", "sortRadio", font=GUI_FONT, enable_events=True, default=True, metadata="title"),
                               sg.Radio("Channel", "sortRadio", font=GUI_FONT, enable_events=True, metadata="channel"),
                               sg.Radio("Date", "sortRadio", font=GUI_FONT, enable_events=True, metadata="date"),
                               sg.Radio("Time", "sortRadio", font=GUI_FONT, enable_events=True, metadata="time"),
                               sg.Radio("Size", "sortRadio", font=GUI_FONT, enable_events=True, metadata="size"),
                               sg.Radio("Duration", "sortRadio", font=GUI_FONT, enable_events=True, metadata="duration"),
                               sg.Radio("drop", "sortRadio", font=GUI_FONT, enable_events=True, metadata="attr_dropped"),
                               sg.Radio("good", "sortRadio", font=GUI_FONT, enable_events=True, metadata="attr_good"),
                               sg.Radio("mastered", "sortRadio", font=GUI_FONT, enable_events=True, metadata="attr_mastered"),
                               sg.Radio("COUNT", "sortRadio", font=GUI_FONT, enable_events=True, metadata="count"),],
                              [sg.Radio("AVG(size)", "sortRadio", font=GUI_FONT, enable_events=True, metadata="avg_size"),
                               sg.Radio("MAX(size)", "sortRadio", font=GUI_FONT, enable_events=True, metadata="max_size"),
                               sg.Radio("SUM(size)", "sortRadio", font=GUI_FONT, enable_events=True, metadata="sum_size"),
                               sg.Radio("ANY(drop)", "sortRadio", font=GUI_FONT, enable_events=True, metadata="any_drop"),
                               sg.Radio("ANY(good)", "sortRadio", font=GUI_FONT, enable_events=True, metadata="any_good"),
                               sg.Radio("ANY(mastered)", "sortRadio", font=GUI_FONT, enable_events=True, metadata="any_mastered"),
                               sg.Radio("Resolution", "sortRadio", font=GUI_FONT, enable_events=True, metadata="resolution"),]]),
                               sg.Push(), sg.VerticalSeparator(color="green"), sg.Column([
                              [sg.Radio("ASC", "orderRadio", font=GUI_FONT, enable_events=True, default=True, metadata=SortOrder.ASC)],
                              [sg.Radio("DESC", "orderRadio", font=GUI_FONT, enable_events=True, metadata=SortOrder.DESC)]])],
                              [sg.HorizontalSeparator(color="green")],
                              [sg.Text("SELECT Mode", key="metaText", font=GUI_FONT, text_color="yellow"),
                               sg.VerticalSeparator(color="green"),
                               sg.Text(key="selectionText", font=GUI_FONT, text_color="yellow"),
                               sg.Push(),
                               sg.Input(key="findInput",
                                            size=40,
                                            font=GUI_FONT,
                                            do_not_clear=False,
                                            disabled=True),
                               sg.VerticalSeparator(color="green"),
                               sg.Button("Drop", key="dropButton")],]),
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
    window = sg.Window(title="Enigma2 DVR Manager",
                       layout=gui_layout,
                       return_keyboard_events=True,
                       resizable=True,
                       finalize=True)

    window["recordingBox"]       .set_focus()
    window["recordingBox"].widget.config(fg="white", bg="black")
    window["commentMul"]  .widget.config(fg="white", bg="black")
    window["findInput"]   .widget.config(fg="white", bg="black")

def gui_find(find_string: str) -> int:
    matches = []
    for i, e in enumerate(global_entrylist):
        if e.groupkey.startswith(make_groupkey(find_string)):
            matches.append(i)

    if len(matches) > 0:
        window["recordingBox"].widget.see(matches[0])

    return len(matches)

def gui_recolor(window: sg.Window) -> None:
    for i, e in enumerate(global_entrylist):
        if isinstance(e, Download):
            window["recordingBox"].widget.itemconfig(i, fg="black", bg="yellow")
            continue

        if e.is_dropped:
            window["recordingBox"].widget.itemconfig(i, fg="white", bg="red")
            continue

        if e.is_mastered:
            window["recordingBox"].widget.itemconfig(i, fg="white", bg="blue")
            continue

        if not e.hd():
            window["recordingBox"].widget.itemconfig(i, fg="grey", bg="black")
            continue

        if e.is_good:
            window["recordingBox"].widget.itemconfig(i, fg="black", bg="light green")
            continue

        window["recordingBox"].widget.itemconfig(i, fg="white", bg="black")

def gui_reselect(entries: list[Entry]) -> None:
    jump_indices = [i for i, e in enumerate(global_entrylist) if e in entries]
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
                downloads(file_basename VARCHAR PRIMARY KEY,
                  groupkey VARCHAR, file_size INT,
                  dl_source VARCHAR, dl_title VARCHAR, dl_description VARCHAR,
                  video_duration INT, video_height INT, video_width INT, video_fps INT,
                  comment VARCHAR);
              """)

def db_load_rec(basename: str) -> Optional[Recording]:
    c = database.cursor()
    c.execute("""
              SELECT file_basename,
                     file_size,
                     epg_channel, epg_title, epg_description,
                     video_duration, video_height, video_width, video_fps,
                     is_good, is_dropped, is_mastered,
                     groupkey,
                     comment,
                     timestamp
              FROM recordings
              WHERE file_basename = ?;
              """, (basename, ))

    if (raw := c.fetchone()) is None:
        return None

    rec = Recording()

    rec.file_basename = raw[0]
    rec.file_size     = raw[1]

    rec.epg_channel,    rec.epg_title,    rec.epg_description               = raw[2], raw[3],  raw[4]
    rec.video_duration, rec.video_height, rec.video_width,    rec.video_fps = raw[5], raw[6],  raw[7], raw[8]
    rec.is_good,        rec.is_dropped,   rec.is_mastered                   = raw[9], raw[10], raw[11]

    rec.groupkey  = raw[12]
    rec.comment   = raw[13]
    rec.timestamp = raw[14]

    return rec

def db_load_dl_all() -> Optional[list[Download]]:
    c = database.cursor()
    c.execute("""
              SELECT file_basename,
                     dl_source, dl_title, dl_description,
                     video_duration, video_height, video_width, video_fps,
                     groupkey,
                     comment,
                     file_size
              FROM downloads;
              """)

    if len(all_raw := c.fetchall()) == 0:
        return None

    all_downloads = []
    for raw in all_raw:
        dl = Download()

        dl.file_basename = raw[0]

        dl.dl_source,      dl.dl_title,     dl.dl_description              = raw[1], raw[2], raw[3]
        dl.video_duration, dl.video_height, dl.video_width,   dl.video_fps = raw[4], raw[5], raw[6], raw[7]

        dl.groupkey  = raw[8]
        dl.comment   = raw[9]
        dl.file_size = raw[10]

        all_downloads.append(dl)

    return all_downloads

def db_load_rec_mastered_all() -> Optional[list[Recording]]:
    c = database.cursor()
    c.execute("""
              SELECT file_basename,
                     file_size,
                     epg_channel, epg_title, epg_description,
                     video_duration, video_height, video_width, video_fps,
                     is_good, is_dropped, is_mastered,
                     groupkey,
                     comment,
                     timestamp
              FROM recordings
              WHERE is_mastered = TRUE;
              """)

    if len(all_raw := c.fetchall()) == 0:
        return None

    all_mastered = []
    for raw in all_raw:

        rec = Recording()

        rec.file_basename = raw[0]
        rec.file_size     = raw[1]

        rec.epg_channel,    rec.epg_title,    rec.epg_description               = raw[2], raw[3],  raw[4]
        rec.video_duration, rec.video_height, rec.video_width,    rec.video_fps = raw[5], raw[6],  raw[7], raw[8]
        rec.is_good,        rec.is_dropped  , rec.is_mastered                   = raw[9], raw[10], raw[11]

        rec.groupkey  = raw[12]
        rec.comment   = raw[13]
        rec.timestamp = raw[14]

        all_mastered.append(rec)

    return all_mastered

def db_save_rec(rec: Recording) -> None:
    assert isinstance(rec, Recording)
    db_remove_rec(rec)
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

def db_save_dl(dl: Download) -> None:
    assert isinstance(dl, Download)
    db_remove_dl(dl)
    c = database.cursor()
    c.execute("""
              INSERT INTO downloads(file_basename, file_size,
                dl_source, dl_title, dl_description,
                video_duration, video_height, video_width, video_fps,
                groupkey, comment)
              VALUES (?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?);
              """, (dl.file_basename, dl.file_size,
                    dl.dl_source, dl.dl_title, dl.dl_description,
                    dl.video_duration, dl.video_height, dl.video_width, dl.video_fps,
                    dl.groupkey, dl.comment))

    database.commit()

def db_remove_rec(rec: Recording) -> None:
    assert isinstance(rec, Recording)
    c = database.cursor()
    c.execute("""
              DELETE FROM recordings
              WHERE file_basename = ?
              """, (rec.file_basename, ))

    assert c.rowcount <= 1
    database.commit()

def db_remove_dl(dl: Download) -> None:
    assert isinstance(dl, Download)
    c = database.cursor()
    c.execute("""
              DELETE FROM downloads
              WHERE file_basename = ?
              """, (dl.file_basename, ))

    assert c.rowcount <= 1
    database.commit()

def get_files_in_directory(directory_path: str, file_extensions: tuple[str]) -> list[str]:
    files = []
    try:
        for f in os.listdir(directory_path):
            file_path = os.path.join(directory_path, f)

            if os.path.isdir(file_path):
                files += get_files_in_directory(file_path, file_extensions)
                continue

            if not os.path.isfile(file_path):
                continue

            if f.endswith(file_extensions):
                files.append(file_path)
    except PermissionError:
        pass

    return files

def scan_directories(dirs: list[str], file_extensions: list[str]) -> list[str]:
    print("Scanning directories... (This may take a while)", file=sys.stderr)

    files = []
    for i, d in enumerate(dirs):
        print(f"Scanning directory: {i + 1} of {len(dirs)}", end="\r", file=sys.stderr)
        files += get_files_in_directory(d, tuple(file_extensions))

    print(f"Successfully scanned {len(dirs)} directories.", file=sys.stderr)

    return files

def process_recordings(files: list[str]) -> None:
    print("Processing recordings... (This may take a while)", file=sys.stderr)

    db_count = 0
    for i, f in enumerate(files):
        print(f"Processing recording {i + 1} of {len(files)}", end="\r", file=sys.stderr)
        basepath = os.path.splitext(f)[0]
        if (rec := RecordingFactory.from_database(basepath)) is not None:
            global_entrylist.append(rec)
            db_count += 1
            continue

        if (rec := RecordingFactory.from_meta_file(basepath, E2_META_EXTENSION)) is not None:
            db_save_rec(rec)
            global_entrylist.append(rec)

    # Always load mastered recordings from database, even if they are deleted
    deleted = [rec for rec in RecordingFactory.from_database_mastered_all() if rec not in global_entrylist]
    global_entrylist.extend(deleted)

    print(f"Recordings successfully processed: {len(global_entrylist)} total entries | {len(files)} files ({db_count} in cache, {len(files) - db_count} new) and {len(deleted)} deleted after mastering", file=sys.stderr)

def process_downloads(files: list[str]) -> None:
    print("Processing downloads... (This may take a while)", file=sys.stderr)

    all_downloads = DownloadFactory.from_database_all()

    db_count = 0
    for i, f in enumerate(files):
        print(f"Processing downloads {i + 1} of {len(files)}", end="\r", file=sys.stderr)
        basepath, file_extension = os.path.splitext(f)
        basename = os.path.basename(basepath)
        match = [d for d in all_downloads if d.file_basename == basename]
        assert len(match) <= 1
        if len(match) == 1:
            match[0].basepath       = basepath
            match[0].file_extension = file_extension

            global_entrylist.append(match[0])
            db_count += 1
            continue

        dl = DownloadFactory.from_video_file(basepath, file_extension)
        db_save_dl(dl)
        global_entrylist.append(dl)

    print(f"Downloads successfully processed: {len(global_entrylist)} total entries | {len(files)} files ({db_count} in cache, {len(files) - db_count} new) ", file=sys.stderr)

def main() -> None:
    db_init()

    with open("config.json") as f:
        config = json.load(f)

    # Crawl directory tree for recordings, search cache, add them to the list
    process_recordings(scan_directories(config["rec_paths"], [E2_VIDEO_EXTENSION]))
    process_downloads(scan_directories(config["dl_paths"], [".mp4"]))

    radios_metadata = ("title", SortOrder.ASC)
    sort_global_entrylist(*radios_metadata)
    radios_metadata_previous = radios_metadata

    gui_init()

    while True:
        selected_recodings = [r for r in global_entrylist if (isinstance(r, Recording) and r.is_dropped)]
        good_recodings     = [r for r in global_entrylist if (isinstance(r, Recording) and r.is_good)]
        mastered_recodings = [r for r in global_entrylist if (isinstance(r, Recording) and r.is_mastered)]

        radios_metadata = tuple(r.metadata for r in window.element_list() if isinstance(r, sg.Radio) and r.get())
        if isinstance(radios_metadata[0], SortOrder):
            radios_metadata = radios_metadata[::-1]

        if radios_metadata != radios_metadata_previous:
            recordingBox_selected_rec = window["recordingBox"].get()
            sort_global_entrylist(*radios_metadata)
            window["recordingBox"].update(global_entrylist)
            if len(recordingBox_selected_rec) > 0:
                gui_reselect(recordingBox_selected_rec)
            radios_metadata_previous = radios_metadata


        window["informationText"].update(f"{len(selected_recodings)} entries (approx. {to_GiB(sum(r.file_size for r in selected_recodings)):.1f} GiB) selected for drop | {len(good_recodings)} good | {len(mastered_recodings)} mastered | {len(global_entrylist)} total")

        gui_recolor(window)
        event, _ = window.read()

        if event == sg.WIN_CLOSED:
            sys.exit()

        recordingBox_selected_rec = window["recordingBox"].get()

        if len(recordingBox_selected_rec) > 0:
            r = recordingBox_selected_rec[0]
            window["metaText"]     .update(f"{r.video_width:4d}x{r.video_height:4d} @ {r.video_fps} fps")
            window["selectionText"].update(f"{len(recordingBox_selected_rec)} entries under cursor")
            window["commentMul"]   .update(recordingBox_selected_rec[0].comment)

        # [C]omment
        if ((event == "c:54" and len(recordingBox_selected_rec) == 1)
        or ( event == "C:54" and len(recordingBox_selected_rec) >  0)):
            window["recordingBox"].update(disabled=True)
            window["dropButton"]  .update(disabled=True)
            window["metaText"]    .update("COMMENT Mode | Submit: [ESC]")
            window["commentMul"]  .update(disabled=False)
            window["commentMul"]  .set_focus()

            while True:
                event, _ = window.read()

                if event == sg.WIN_CLOSED:
                    sys.exit()

                if event != "Escape:9":
                    continue

                comment = window["commentMul"].get()
                break

            window["commentMul"]  .update(disabled=True)
            window["dropButton"]  .update(disabled=False)
            window["metaText"]    .update("SELECT Mode")
            window["recordingBox"].update(disabled=False)
            update_attribute(recordingBox_selected_rec,
                             lambda r: True,
                             lambda r: setattr(r, "comment", comment))
            window["recordingBox"].set_focus()
            continue

        # [F]ind
        if event == "f:41":
            window["recordingBox"].update(disabled=True)
            window["dropButton"]  .update(disabled=True)
            window["metaText"]    .update("FIND Mode | Submit: [ESC]")
            window["findInput"]   .update("", disabled=False)
            window["findInput"]   .set_focus()

            while True:
                event, _ = window.read()

                if event == sg.WIN_CLOSED:
                    sys.exit()

                matches_found = gui_find(window["findInput"].get())
                window["selectionText"].update(f"{matches_found} matching entries found")

                if event == "Escape:9":
                    break

            window["findInput"]   .update(disabled=True)
            window["dropButton"]  .update(disabled=False)
            window["metaText"]    .update("SELECT Mode")
            window["recordingBox"].update(disabled=False)
            window["recordingBox"].set_focus()
            continue

        # [I]nformation from EIT entry
        if event == "i:31" and len(recordingBox_selected_rec) == 1:
            if (isinstance(recordingBox_selected_rec[0], Download)):
                continue
            sg.popup(get_eit_data(recordingBox_selected_rec[0]),
                     title=f"EIT - {recordingBox_selected_rec[0].epg_title}",
                     font=GUI_FONT,
                     any_key_closes=True,
                     location=window.current_location())
            continue

        # [O]pen recording using VLC
        if event == "o:32" and len(recordingBox_selected_rec) > 0:
            if (bp := recordingBox_selected_rec[0].basepath) is not None:
                if isinstance(recordingBox_selected_rec[0], Recording):
                    subprocess.Popen(["vlc", bp + E2_VIDEO_EXTENSION])
                else:
                    subprocess.Popen(["vlc", bp + recordingBox_selected_rec[0].file_extension])
            continue

        # Select for [D]rop
        if event == "d:40":
            if (isinstance(recordingBox_selected_rec[0], Download)):
                continue
            update_attribute(recordingBox_selected_rec,
                             lambda r: not r.is_mastered,
                             lambda r: setattr(r, "is_dropped", True))
            continue

        if event == "D:40":
            if (isinstance(recordingBox_selected_rec[0], Download)):
                continue
            update_attribute(recordingBox_selected_rec,
                             lambda r: r.is_dropped ,
                             lambda r: setattr(r, "is_dropped", False))
            continue

        # Mark recording as [G]ood
        if event == "g:42":
            if (isinstance(recordingBox_selected_rec[0], Download)):
                continue
            update_attribute(recordingBox_selected_rec,
                             lambda r: not r.is_good,
                             lambda r: setattr(r, "is_good", True))
            continue

        if event == "G:42":
            if (isinstance(recordingBox_selected_rec[0], Download)):
                continue
            update_attribute(recordingBox_selected_rec,
                             lambda r: r.is_good,
                             lambda r: setattr(r, "is_good", False))
            continue

        # Mark recording as [M]astered
        if event == "m:58":
            if (isinstance(recordingBox_selected_rec[0], Download)):
                continue
            update_attribute(recordingBox_selected_rec,
                             lambda r: not r.is_dropped,
                             lambda r: setattr(r, "is_mastered", True))
            continue

        if event == "M:58":
            if (isinstance(recordingBox_selected_rec[0], Download)):
                continue
            update_attribute(recordingBox_selected_rec,
                             lambda r: r.is_mastered,
                             lambda r: setattr(r, "is_mastered", False))
            continue

        # Drop button pressed
        if event == "dropButton":
            for_deletion = set()
            for e in [x for x in global_entrylist if isinstance(x, Recording) and x.is_dropped]:
                drop_recording(e)
                for_deletion.add(e)
            for e in for_deletion:
                global_entrylist.remove(e)
            window["recordingBox"].update(global_entrylist)

if __name__ == "__main__":
    main()
