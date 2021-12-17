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

# Installation
Requirements:
- odr-audioenc (DAB/DAB+ Encoder)
- odr-padenc (DAB PAD Encoder)
- odr-dabmux (DAB Multiplexer)
- odr-dabmod (DAB Modulator)
- dialog (TUI)
- Python 3.9+
- python-pyttsx3 (TTS)
- python-pydub (Convert mp3 TTS output to wav)
- python-pythondialog (TUI)
- python-Flask (HTTP server)

TODO

# Configuration
TODO

# Warning method
TODO

# TODO
- [x] Automatically create fifo
- [x] Stream class
- [x] Stream management
- [ ] Implement stream replacement without use of external scripts
- [ ] TTS
- [ ] Manual announcement triggering
- [ ] GUI config - Ensemble announcement
- [ ] GUI config - Service PTY and Announcement
- [ ] GUI config - Subchannels
- [ ] GUI config - Stream
- [ ] Settings - CAP identity
- [ ] Logging - Add stream logs to GUI
