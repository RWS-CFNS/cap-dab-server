cap-dab-server is a piece of software that combines exisiting technologies
(ODR-mmbTools) into a solution capable of translating CAP (Common
Alerting Protocol) messages to a DAB/DAB+ emergency warning broadcast.

Features include:
- A TUI management interface to view status, logs and configure general settings
- Simple TUI configuration of the DAB multiplexer
- Option to send warning messages using the DAB Alarm announcement or "old
  school" stream replacement (see also "Warning method").
- Ability to switch channel's stream sources on the fly
- Spoken (Text To Speech) CAP description

![Main menu](main_menu.png)

# Installation
Requirements:
- dialog (TUI)
- ffmpeg (Convert mp3 TTS output to wav)
- odr-audioenc (DAB/DAB+ Encoder)
- odr-padenc (DAB PAD Encoder)
- odr-dabmux (DAB Multiplexer)
- odr-dabmod (DAB Modulator)
- Python 3.9+
- python-Flask (HTTP server)
- python-pyttsx3 (TTS)
- python-pythondialog (TUI)
- python-pyzmq (IPC with ODR-mmbTools)

## Debian/Ubuntu
```
$ sudo apt install dialog ffmpeg python3 python3-pip
$ pip3 install --user flask pyttsx3 pythondialog
```

## macOS
```
$ brew install dialog ffmpeg python
$ pip3 install --user flask pyttsx3 pythondialog
```

## Windows
TODO

# Configuration
TODO

# Warning method
TODO

# TODO
- [x] Automatically create fifo
- [x] Stream class
- [x] Stream management
- [x] Implement stream replacement without use of external scripts
- [x] TTS
- [x] Implement ability to cancel announcements
- [ ] Configurable label, pty and such for stream replacement/alarm channel
- [ ] Manual announcement triggering
- [ ] GUI config - Ensemble announcement
- [ ] GUI config - Service PTY and Announcement
- [ ] GUI config - Subchannels
- [ ] GUI config - Stream
- [ ] GUI config - DAB modulator
- [ ] Settings - CAP identity
- [ ] Logging - Add stream logs to GUI
- [x] Option to use ODR-DabMod config file instead of fifo output
- [ ] Option to restart threads that have quit
- [x] Use ZeroMQ ipc instead of telnet for communication with odr-dabmux

# License
This project is licensed under the GNU General Public License v3.0. See
`LICENSE` for more information.

# Credits
Credits to [OpenDigitalRadio](http://www.opendigitalradio.org/) for the
excellent open-source ODR-mmbTools DAB/DAB+ software tools.

Credit to Adeola Bannis of the University of California for [BoostInfoParser](https://gist.github.com/thecodemaiden/dc4e4e4a54eaa5f0be84).
