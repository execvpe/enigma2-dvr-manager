# Engima2 DVR Manager

The Enigma2 **D**irect **V**ideo **R**ecording Manager is a GUI-based tool for managing, sorting 
and selectively deleting (duplicate) TV recordings made by an Enigma2 Linux-based TV recorder.

## Disclaimer

### This program is still a work in progress!

Features may be deleted or changed in functionality without further notice.  
It may be that the documentation below is not updated in time and therefore
may not document the real behavior of the program.

If so, please let me know or open a Pull Request with a suitable correction.  
Any help is appreciated. :)

### Use this software at your own risk!

**I am not responsible** if you use this program (wrongly) and/or
destroy important files on your system.

**Always** check the file paths **before** deleting to be sure everything is correct!

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

There should be a similar way of installation if you are using another distribution or Windows.

## Usage

Launch the program in your shell and supply all directory paths in which recordings are stored
as the program arguments (see [example](#Example) below).
There is currently no option to add or manage loaded directories via the GUI.

```shell
./dvr_manager.py <dir path> [dir path...]
```

| Keyboard Shortcut | Explanation |
| :---------------: | :---------: |
| O         | Open the first of the selected recordings in VLC |
| C         | Add or change the comment of one selected recording |
| Shift + C | Add or change the comment of the first recording and **overwrite the comments of all recordings under the cursor** with this one |
| D         | Select all recordings under the cursor for drop / Apply the D attribute to the selected recordings |
| Shift + D | Remove the D attribute from the selected recordings |
| G         | Mark recording as good / Apply the G attribute to the selected recordings |
| Shift + G | Remove the G attribute from the selected recordings |
| M         | Mark recording as mastered / Apply the M attribute to the selected recordings |
| Shift + M | Remove the M attribute from the selected recordings |

**If a recording is marked as mastered, it cannot be dropped and vice versa.**

If you press the `Drop` button, the file paths of all files belonging
to all recordings marked with the D attribute are written into the file
`dropped` in the directory of this program.

You can review the files again and then delete them manually or using:
```shell
xargs -d '\n' -n 1 rm -vf < dropped
```

**[Deletion is permanent](#disclaimer)! So be careful what you delete!**

If you restart the software without deleting/moving your dropped recordings,
they will reappear in the recording list, but **without any previously set attributes**
or comments, as any metadata will be purged from the local database when pressing `Drop`.

If you are not yet confident about deletion,
you can move the files to another directory to circumvent this behavior:
```shell
mkdir -p DROPPED_RECORDINGS && xargs -d '\n' -n 1 mv -vt DROPPED_RECORDINGS < dropped
```

## Example

```shell
./dvr_manager.py /mnt/hdd/dvr/movies /mnt/nas/recordings
Scanning directories... (This may take a while)
Successfully scanned 2 directories.
Processing recordings... (This may take a while)
Successfully processed 4821 recordings. (4723 in cache, 98 new)
```
