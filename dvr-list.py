#!/usr/bin/env python3

from datetime import datetime
import re as regex
import sys

recordings = []

class Recording:
    def __init__(self, meta):
            self.channel     = meta[0].split(":")[-1].strip()
            self.sortkey     = alphanumeric(meta[1]).lower()
            self.title       = meta[1].strip()
            self.description = remove_prefix(meta[2].strip(), self.title)[:24].strip()
            self.timestamp   = datetime.fromtimestamp(int(meta[3]))
            self.length      = int(int(meta[5].strip()) / 90_000)
            self.hd          = "hd" in self.channel.lower()


    def __repr__(self):
        return f"{format_length(self.length)} | {'HD' if self.hd else '  '} | {self.title} | {self.description}"

def alphanumeric(line: str) -> str:
    return regex.sub("[^A-Za-z0-9]+", "", line)

def format_length(seconds) -> str:
    minutes = seconds / 60
    return f"{int(minutes / 60)}h {int(minutes % 60):02d}'"

def remove_prefix(line: str, prefix: str):
    return regex.sub(r'^{0}'.format(regex.escape(prefix)), '', line)

def main(argc: int, argv: list[str]) -> None:
    print("Waiting for meta files or EOF")
    while True:
        try:
            with open(input()) as f:
                recordings.append(Recording(f.readlines()))
        except EOFError:
            print("EOF received")
            break

    print("Begin sorting...")
    recordings.sort(key=lambda r: r.sortkey)
    print("Sorting finished")

    for r in recordings:
        print(r)

if __name__ == "__main__":
    main(len(sys.argv), sys.argv)
