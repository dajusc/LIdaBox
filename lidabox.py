#!/usr/bin/env python
# -*- coding: utf8 -*-
#
# To configure autostart at PasPi-userlogin, just create "/etc/xdg/autostart/lidabox.desktop" containing:
# > [Desktop Entry]
# > Name=LIdaBox
# > Exec=lxterminal --working-directory="/<PATHTO>/lidabox/" --command="python lidabox.py"

"""@package lidabox
    ~~~ LIdaBox by David Schaefer for his daugther ~~~

    A RasPi application for a RFID controlled Google-Play-Music (GPM) musicbox.
    The user can store the names of GPM-playlists on RFID-tags, or he can link
    RFID-tag-UIDs to playlist names. Once the RC522-RFID-reader attached to the
    RasPi detects a corresponding tag, it starts playing the playlist. The
    playback is stopped when the end of the playlist is reached or when the tag
    is removed.

    To configure autostart at RasPi-userlogin, just create
    "/etc/xdg/autostart/lidabox.desktop" containing:
    > [Desktop Entry]
    > Name=LIdaBox
    > Exec=lxterminal --working-directory="/<PATHTO>/lidabox/" --command="python lidabox.py"
"""

import os, sys, string
sys.path.append('../libraries/MFRC522-python.git/')
import MFRC522   # https://github.com/mxgxw/MFRC522-python
import gmusicapi # pip install gmusicapi
import vlc       # pip install python-vlc
import time
import RPi.GPIO

#--

class lidabox:
    def __init__(self, email, passw, andid, tokdic={}, debug=True):
        self.play_mp3("start.mp3")

        self.email         = email
        self.passw         = passw
        self.andid         = andid
        self.tokdic        = tokdic
        self.debug         = debug
        self.uid           = None # UID of RFID-card
        self.token         = None # name of item to be played (gpm-playlist-name)
        self.tracks        = []   # list of tracks (current playlist)
        self.tolreadfails  = 0    # tolerated RFID read fails

        self.myprint("Connecting with Google Play Musik...")
        self.gpm_client    = gmusicapi.Mobileclient()
        self.gpm_logged_in = self.login_gpm()

        self.myprint("Initializing VLC mediaplayer...")
        self.vlc_player    = vlc.MediaPlayer()

        self.myprint("Initializing RFID reader...")
        self.rfid_client = MFRC522.MFRC522()
        if not self.debug:
            RPi.GPIO.setwarnings(False)


    def __del__(self):
        self.stop_and_clear()
        self.gpm_client.logout()
        RPi.GPIO.cleanup()


    def myprint(self, text):
        if self.debug:
            print text


    def play_mp3(self, path, block=False):
        """Playback a local audio file."""
        path = os.path.abspath(path)
        if os.path.exists(path):
            mp = vlc.MediaPlayer(path)
            mp.play()
            if block:
                while mp.get_state() in [vlc.State.NothingSpecial, vlc.State.Opening, vlc.State.Buffering, vlc.State.Playing]:
                    time.sleep(.1)
                time.sleep(.1)


    def login_gpm(self):
        """Log into Google and fetch all user playlits from Google Play Music."""
        logged_in = self.gpm_client.login(self.email, self.passw, self.andid, locale="de_DE")

        if logged_in:
            self.gpm_plli = self.gpm_client.get_all_user_playlist_contents() # list of gpm-playlists
        else:
            self.myprint("ERROR: Could not login to Google!")

        return logged_in


    def get_rfid_data(self, cli=None, raw=False, quit_on_uid=None, debug=False):
        """Read RFID-tag and return UID and contained data. If reading fails, return None."""
        if cli == None:
            cli=self.rfid_client

        data = {}

        def select_tag(cli, serNum):
            buf =  [cli.PICC_SElECTTAG, 0x70] + serNum[:5]
            buf += cli.CalulateCRC(buf)[:2]
            (status, backData, backLen) = cli.MFRC522_ToCard(cli.PCD_TRANSCEIVE, buf)
            if (status == cli.MI_OK) and (backLen == 0x18):
                return backData[0]
            else:
                return 0

        def read_block(cli, blksiz, blkid):
            recvData =  [cli.PICC_READ, blksiz*blkid]
            recvData += cli.CalulateCRC(recvData)[:2]
            (status, backData, backLen) = cli.MFRC522_ToCard(cli.PCD_TRANSCEIVE, recvData)
            if status == cli.MI_OK:
                return (status, backData, backLen)
            else:
                return (status, None, 0)

        def block_to_str(data):
            data = [str(chr(d)) for d in data]
            data = [d for d in data if d in string.printable]
            data = str(''.join(data))
            return data

        (status, TagType) = cli.MFRC522_Request(cli.PICC_REQIDL)

        if status != cli.MI_OK:
            (status, TagType) = cli.MFRC522_Request(cli.PICC_REQIDL) # first request often fails

        (status, uid) = cli.MFRC522_Anticoll()

        if status != cli.MI_OK:
            return None

        if quit_on_uid != None and uid == quit_on_uid:
            data["uid"]     = uid
            data["strdata"] = None
            return data

        if debug:
            print "---------------------------------------------------------------"
            print "Card UID:    %s, %s, %s, %s" % (uid[0], uid[1], uid[2], uid[3])

        blksiz = select_tag(cli, uid) # cli.MFRC522_SelectTag(uid) does the same, but spamms stdout

        blkdata = []
        for blkid in range(50):
            (status, backData, backLen) = read_block(cli, blksiz, blkid)
            if backData != None:
                blkdata += backData
            else:
                break

        while len(blkdata) > 0 and blkdata[-1] == 0:
            blkdata = blkdata[:-1] # remove trailing zeros

        if not raw:
            while len(blkdata) > 0 and blkdata[-1] == 254:
                blkdata = blkdata[:-1] # remove trailing EOL-char
            if 2 in blkdata:
                ind = blkdata.index(2)+3
                blkdata = blkdata[ind:]

        strdata = block_to_str(blkdata).strip()

        if debug:
            print "Data (int): ", blkdata
            print "Data (str): ", strdata

        data["uid"]     = uid
        data["strdata"] = strdata

        return data


    def update_token(self):
        """Update token depending on the returnvalue of the RFID-reader."""
        lastuid              = self.uid
        last_token_was_valid = self.token_is_valid()

        data = self.get_rfid_data(quit_on_uid=self.uid)

        if data != None:
            self.tolreadfails = 0 # set number of tolerated RFID read fails
        elif lastuid != None and self.tolreadfails > 0:
            self.myprint("Token read fail (tolerated).")
            self.tolreadfails -= 1
            return # read fail is tolerated --> return

        if data != None:
            self.uid = data["uid"]
            if self.uid != lastuid: # only update token if uid changed
                self.token = data["strdata"]
            self.uid_to_token() # if uid has entry in tokdic, override token
        else:
            self.uid   = None
            self.token = None

        if self.uid == lastuid:
            return # nothing changed --> return

        elif self.uid == None:
            self.myprint("Token was removed.")
            self.stop_and_clear()
            if last_token_was_valid:
                self.play_mp3("stop.mp3", block = True)
            self.myprint("Waiting for token...")

        else:
            self.myprint("Token detected: \"{}\" (UID: {}).".format(self.token, self.uid))
            if self.token_is_valid():
                self.play_mp3("found.mp3", block = True)
                self.token_to_tracks()
            else:
                self.myprint("Token invalid!")
                self.play_mp3("invalid.mp3", block = True)


    def uid_to_token(self, override=True):
        """If UID is contained in token dictionary, change token accordingly."""
        if self.uid not in self.tokdic:
            return
        if not override and self.token != None:
            return
        self.token = self.tokdic.get(self.uid, None)


    def token_is_valid(self):
        """Check if token is a valid Google-Play-Music playlist name."""
        pl_names = [pl["name"].lower() for pl in self.gpm_plli]
        return str(self.token).lower() in pl_names


    def token_to_tracks(self):
        """Fill up playlist according to current token."""
        if self.token_is_valid():
            for pl in self.gpm_plli:
                if str(self.token).lower() in pl["name"].lower():
                    self.halt   = True
                    self.tracks = list(pl["tracks"]) # list-items are still pointer! (copy.deepcopy would be too slow)
                    self.myprint("Playlist has {} titles.".format(len(self.tracks)))
                    for tra in self.tracks:
                        tra["url"] = None
                    break
        else:
            self.myprint("ERROR: Playlist not found!")
            self.stop_and_clear()


    def track_fetch_url(self, ind=0, force=True):
        """Fetch VLC compatible streaming URL from Google-Play-Music."""
        if ind < 0 or ind > len(self.tracks)-1: # index out of range
            return

        tra = self.tracks[ind]
        url = tra.get("url", None)
        if url != None and force == False:
            return

        tid = tra.get("storeId", tra.get("trackId", tra.get("id", tra.get("nid", None))))
        try:
            url = self.gpm_client.get_stream_url(tid, self.andid)
        except:
            url = None
            self.myprint("WARNING: Could not get URL for title \"{}\"".format(tra.get("title", "UNKNOWN")))

        self.tracks[ind]["url"] = url


    def play_tracks(self):
        """Playback all tracks in playlist."""
        numtra = len(self.tracks)
        self.halt = False
        self.myprint("Starting playlist...")

        while len(self.tracks) > 0 and not self.halt:
            self.track_fetch_url(0, force=False) # fetch url for current title, if not already fetched
            tra = self.tracks[0]
            url = tra["url"]
            tit = tra.get("track", {}).get("title", "UNKNOWN")

            self.myprint("Playing title {}/{} \"{}\"".format(1+numtra-len(self.tracks) , numtra, tit))
            if url != None:
                self.vlc_player.stop()
                self.vlc_player.set_mrl(url)
                self.vlc_player.play()

                while self.vlc_player.get_state() in [vlc.State.NothingSpecial, vlc.State.Opening, vlc.State.Buffering]:
                    time.sleep(.1)

                play_time_url  = self.vlc_player.get_length()*1e-3 - 5 # 5 seconds before title ends
                real_time_rfid = time.time() + 1

                while self.vlc_player.get_state() in [vlc.State.Playing, vlc.State.Paused] and not self.halt:
                    time.sleep(.1)

                    if self.vlc_player.get_time()*1e-3 > play_time_url:
                        # self.myprint("Fetching URL for next title...")
                        self.track_fetch_url(1) # prefetching url for next title
                        play_time_url += 10000

                    if time.time() > real_time_rfid:
                        self.update_token()
                        real_time_rfid = time.time() + 1

                if self.vlc_player.get_state() in [vlc.State.Error]:
                    self.myprint("ERROR: Playlist stopped unexpectingly!")

                if self.halt:
                    self.vlc_player.stop()
                    return

            if len(self.tracks):
                del(self.tracks[0])

        if len(self.tracks) == 0 and not self.halt:
            self.myprint("Playlist finished normaly.")


    def stop(self):
        """Stop playback."""
        self.halt     = True
        self.vlc_player.stop()


    def stop_and_clear(self):
        """Stop playback and reset everything by deleting UID, token and playlist."""
        self.stop()
        self.uid    = None
        self.token  = None
        self.tracks = []


    def loop(self):
        """Main loop of the LIdaBox."""
        if not self.gpm_logged_in:
            self.myprint("ERROR: Not connected with Google Play Musik!")
            return None

        self.myprint("Waiting for token...")
        while True:
            self.update_token()
            if len(self.tracks) == 0:
                time.sleep(1)
            else:
                self.play_tracks()

#--

if __name__ == "__main__":
    print "###################################################################"
    print "Starting LIdaBox..."

    email = "yourname@gmail.com" # Google-Account-Username or -email
    passw = "abcdefghijklmnopqr" # Google-App-Password (https://support.google.com/accounts/answer/185833)
    andid = "0123456789abcdef"   # Valid Android-ID registered to given Google-Account
    tokdic = {[0,0,0,0,0]: "MyPlaylistName"} # Dictionary translating RFID-tag-UID to Google-Play-Music-playlist
    tokdic = {[0,0,0,0,0]: "MyPlaylistName"} # Dict translating RFID-tag-UID to Google-Play-Music-playlist

    if "lb" in locals(): del(lb)
    lb = lidabox(email, passw, andid, tokdic)
    lb.loop()
