#!/usr/bin/env python3

import cv2
from datetime import datetime
import re as regex
import sys

recordings = []

class Recording:
    def __init__(self, path: str, meta: str):
        self.path        = path.strip()
        self.channel     = meta[0].split(":")[-1].strip()
        self.sortkey     = alphanumeric(meta[1]).lower()
        self.title       = meta[1].strip()
        self.description = remove_prefix(meta[2].strip(), self.title).strip()
        self.timestamp   = datetime.fromtimestamp(int(meta[3]))
#       self.length      = int(int(meta[5].strip()) // 90_000)
        self.hd          = "hd" in self.channel.lower()
#       self.resolution  = get_video_metadata(path)

    def __repr__(self):
        return f"{self.timestamp.strftime('%H:%M')} | {self.channel[:8].ljust(8)} | {self.title[:43].ljust(43)} | {self.description[:73]}"

def alphanumeric(line: str) -> str:
    return regex.sub("[^A-Za-z0-9]+", "", line)

def format_length(raw: int) -> str:
    hours   = raw // 3_600
    raw -= hours * 3_600
    minutes = raw // 60
    raw -= minutes * 60
    seconds = raw
    return f"{hours}:{minutes:02d}:{seconds:02d}"

def remove_prefix(line: str, prefix: str):
    return regex.sub(r'^{0}'.format(regex.escape(prefix)), '', line)

def get_video_metadata(path: str):
    vid     = cv2.VideoCapture(path)
#   fps     = int(vid.get(cv2.CAP_PROP_FPS))
    quality = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
    return f"{quality}{'p' if quality == 720 else 'i'}".rjust(5)

def main(argc: int, argv: list[str]) -> None:
    print("Waiting for *.ts file paths or EOF")
    while True:
        try:
            path = input()
            with open(path + ".meta") as file:
                recordings.append(Recording(path, file.readlines()))
        except FileNotFoundError:
            continue
        except EOFError:
            break

    recordings.sort(key=lambda r: r.sortkey)

    padding = len(str(len(recordings)))
    for i, r in enumerate(recordings):
        print(f"{str(i).rjust(padding)} | {r}")

if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
