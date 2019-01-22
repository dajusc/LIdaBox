# LIdaBox
A RasPi application for a RFID controlled Google-Play-Music (GPM) musicbox.

## Overview
The user can store the names of GPM-playlists on RFID-tags, or he can link RFID-tag-UIDs to playlist names. 
Once the RC522-RFID-reader attached to the RasPi detects a corresponding tag, it starts playing the playlist. 
The playback is stopped when the end of the playlist is reached or when the tag is removed.

## Run on Raspberry Pi at Startup
Just create "/etc/xdg/autostart/lidabox.desktop" containing:
```
[Desktop Entry]
Name=LIdaBox
Exec=lxterminal --working-directory="/<PATH>/<TO>/<LIdaBox>/" --command="python lidabox.py"
```

## Credits
LIdaBox uses [gmusicapi](https://github.com/simon-weber/gmusicapi) by Simon Weber, [MFRC522-python](https://github.com/mxgxw/MFRC522-python) by mxgxw, and VLC media player.
