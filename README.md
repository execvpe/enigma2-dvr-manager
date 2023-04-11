# Engima2 DVR Manager

The Enigma2 DVR (Direct Video Recordings) Manager is a GUI-based tool for managing, sorting 
and selectively deleting (duplicate) TV recordings made by an Enigma2 Linux-based TV recorder.

## Features

- Minimalistic GUI frontend
- Easy to use (if you like keyboard shortcuts)
- No submenus 
- Comment recordings or keep notes to them
- Mark recordings as good, bad or already mastered
- Read-only operations and no (automatic) deletion,
  so you have full control over your recordings and what you are doing

## Dependencies

- JetBrains Mono font (*you can change the font at the top of `dvr_manager.py`*)
  or any other (monospace) font

- cv2 (tested: 4.7.0-7)
- PySimpleGUI (tested: 4.60.3-1)

If you are using Arch Linux, you can install the dependencies using:  
```shell
pacman -S python-opencv python-pysimplegui [ttf-jetbrains-mono]
```

There should be a simillar way of installation if you are using another distribution or Windows.

## Disclaimer

### Use this software at your own risk!

> This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY [...].

This means especially:  
**I am not responsible** if you use this program (wrongly) and thereby destroy
important files on your system.

***Always*** check the file paths **before** deleting to be sure everything is correct!

## Usage

```shell
./dvr_manager.py <dir path> [dir path...]
```

| Keybind   | Explanation |
| :-------: | -------- |
| O         | Open the first of the selected recordings in VLC       |
| C         | Add a comment to the first of the selected recordings  |
| Shift + C | Change the comment of the first recording and **overwrite the comments of all recordings under the cursor** with this one |
| D         | Select all recordings under the cursor for drop |
| Shift + D | Unselect all recordings under the cursor from drop |
| G         | Mark recording as good / Apply the G attribute to the selected recordings |
| Shift + G | Remove the G attribute from the selected recordings |
| M         | Mark recording as mastered / Apply the M attribute to the selected recordings |
| Shift + M | Remove the M attribute from the selected recordings |

**If a recording is marked as mastered, it cannot be dropped and vice versa.**

If you press the `Drop` button, the file paths of all files belonging
to all recordings marked with the D attribute are written into the file
`dropped` in the directory of this program.
You can review the files again and then delete them manually or using:
```
xargs -d '\n' -n 1 rm -f < dropped
```

**[Deletion is permanent!](#disclaimer) So be careful what you delete!**

## Example

```shell
./dvr_manager.py /mnt/hdd/dvr/movies /mnt/nas/recordings
Scanning directories... (This may take a while)
Successfully scanned 2 directories.
Processing recordings... (This may take a while)
Successfully processed 4821 recordings. (4723 in cache, 98 new)
```
