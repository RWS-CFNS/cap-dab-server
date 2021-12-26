#
#    CFNS - Rijkswaterstaat CIV, Delft © 2021 <cfns@rws.nl>
#
#    Copyright 2021 Bastiaan Teeuwen <bastiaan@mkcl.nl>
#
#    This file is part of cap-dab-server
#
#    cap-dab-server is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    cap-dab-server is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with cap-dab-server. If not, see <https://www.gnu.org/licenses/>.
#

import configparser                 # Python INI file parser
import copy                         # For creating a copy on the Stream configuration
import datetime                     # To get the current date and time
import logging                      # Logging facilities
import os                           # For file I/O
import pyttsx3                      # Text To Speech engine frontend
import queue                        # Queue for passing data to the DAB processing thread
import subprocess as subproc        # For spawning ffmpeg to convert mp3 to wav
import zmq                          # For signalling (alarm) announcements to ODR-DabMux
import threading                    # Threading support (for running Mux and Mod in the background)
from cap.parser import CAPParser    # CAP XML parser (internal)

logger = logging.getLogger('server.dab')

# DAB queue watcher and message processing
# This thread handles messages received from the CAPServer
class DABWatcher(threading.Thread):
    def __init__(self, config, q, zmqsock, streams, muxcfg):
        threading.Thread.__init__(self)

        self.zmq = zmq.Context()

        self.q = q
        self.zmqsock = zmqsock
        self.streams = streams
        self.muxcfg = muxcfg.cfg

        self.alarm = config['warning'].getboolean('alarm')
        self.replace = config['warning'].getboolean('replace')
        self.alarmpath = f'{config["general"]["logdir"]}/streams/sub-alarm'

        self.tts = pyttsx3.init()

        self._running = True

    def run(self):
        # Main a list of currently active announcements with their expiry date
        announcements = []

        # Flag that keeps track of whether the TTS message should be updated
        changed = False

        # Insert silence into TTS depending on the backend that's used by pyttsx3
        def _slnc(ms):
            backend = self.tts.proxy._module.__name__

            # SAPI5 on Windows
            # NSSS on macOS
            # espeak on Linux and other platforms

            if backend == 'pyttsx3.drivers.sapi5':
                return f'<silence msec="{ms}"/>'
            elif backend == 'pyttsx3.drivers.nsss':
                return f'[[slnc {ms}]]'
            elif backend == 'pyttsx3.drivers.espeak':
                return f'<break time="{ms}ms"/>'
            else:
                logger.warn(f'Unsupported TTS backend, please contact the developer: {backend}')
                return ''

        # Connect to the multiplexer ZMQ socket
        muxsock = self.zmq.socket(zmq.REQ)
        muxsock.connect(f'ipc://{self.zmqsock}')

        def mux_send(sock, msg):
            msgs = msg.split(' ')
            res = ''

            # Perform a quick ping test
            sock.send(b'ping')
            data = sock.recv_multipart()
            if data[0].decode() != 'ok':
                return None

            # Send our actual command
            for i, part in enumerate(msgs):
                if i == len(msgs) - 1:
                    f = 0
                else:
                    f = zmq.SNDMORE

                sock.send(part.encode(), flags=f)

            # Wait for the results
            data = sock.recv_multipart()
            for i, part in enumerate(data):
                res += part.decode()

            return res

        while self._running:
            try:
                # Check if there's any expired announcements to be cancelled
                for ann in announcements:
                    # Expires shouldn't be None, as the parser already check it
                    if ann['expires'] == None:
                        # In case it does, remove the announcement from the queue
                        logger.error(f'invalid <expires> timestamp format: {ann["expires"]}')
                        announcements.remove(ann)
                    elif ann['expires'] < datetime.datetime.now(ann['expires'].tzinfo):
                        logger.info(f'Cancelled CAP message: {ann["identifier"]}')
                        announcements.remove(ann)

                # Wait for a message from the CAPServer
                a = self.q.get(block=True, timeout=1)

                # Handle the current message
                if a['msg_type'] == CAPParser.TYPE_ALERT:
                    logger.info(f'New CAP message: {a["identifier"]}')
                    announcements.append(a)
                elif a['msg_type'] == CAPParser.TYPE_CANCEL:
                    cancelled = False

                    # Remove cancelled messages from the list
                    for ref in a['references']:
                        for ann in announcements:
                            if ref['sender']     == ann['sender'] and \
                               ref['identifier'] == ann['identifier'] and \
                               ref['sent']       == ann['sent']:
                                logger.info(f'Cancelled CAP message: {ref["identifier"]}')
                                announcements.remove(ann)
                                cancelled = True

                    # Prevent restarting the stream(s) if no message was cancelled
                    if cancelled == False:
                        logger.warn(f'Invalid CAP cancel request: {ref["identifier"]} {ref["sender"]} {ref["sent"]}')

                        self.q.task_done()
                        continue

                # Generate new TTS message
                num = len(announcements)
                tts_str = ''

                if num == 0:
                    # Stop the alarm announcement and switch services back to their original streams
                    for s, t, c, o in self.streams.streams:
                        # TODO change back dls and label
                        if self.alarm:
                            out = mux_send(muxsock, 'set alarm active 0')
                            logger.info(f'Deactivating alarm announcement, res: {out}')

                        if self.replace:
                            # Restore the old stream
                            self.streams.setcfg(s)

                            service = 'srv-audio' # FIXME don't hardcode, do for each

                            # Restore the original service labels
                            # FIXME generate label if no shortlabel
                            # FIXME settings label errors out if there's spaces
                            label = self.muxcfg.services[service]['label']
                            shortlabel = self.muxcfg.services[service]['shortlabel']
                            pty = self.muxcfg.services[service]['pty']

                            out = mux_send(muxsock, f'set {service} label {label},{shortlabel}')
                            logger.info(f'Restoring original Service Label on service {service}, res: {out}')
                            out = mux_send(muxsock, f'set {service} pty {pty}')
                            logger.info(f'Restoring original PTY on service {service}, res: {out}')

                    self.q.task_done()
                    continue
                elif num == 1:
                    tts_str += f'{_slnc(2000)} {announcements[0]["description"]}. {_slnc(500)} Einde bericht. {_slnc(2000)} Herhaling'
                else:
                    # In the case there's multiple messages in the queue:
                    # Combine them into a single string with start and end markers.
                    for i, ann in enumerate(announcements):
                        # TODO handle other languages
                        tts_str += f'{_slnc(2000)} Bericht {i + 1}. {_slnc(1000)} {a["description"]}. {_slnc(500)} Einde bericht {i + 1}.'
                    tts_str += f'{_slnc(2000)} Herhaling'

                # Generate TTS output from the description
                mp3 = f'{self.alarmpath}/tts.mp3'
                # TODO look for the right language
                self.tts.setProperty('voice', 'com.apple.speech.synthesis.voice.xander')
                self.tts.save_to_file(tts_str, mp3)
                self.tts.runAndWait()

                # Convert the mp3 output to wav, the format supported by odr-audioenc
                # This process also duplicates the mono channel to stereo, bitrate 48000 Hz and s16
                # FIXME handle conditions where the conversion fails
                # TODO output log somewhere
                ffmpeg = subproc.Popen(('ffmpeg',
                                        '-y',
                                        '-i', mp3,
                                        '-acodec', 'pcm_s16le',
                                        '-ar', '48000',
                                        '-ac', '2',
                                        f'{self.alarmpath}/tts.wav'), stdout=subproc.DEVNULL, stderr=subproc.DEVNULL)
                try:
                    ffmpeg_res = ffmpeg.wait(timeout=20)
                except subproc.TimeoutExpired as e:
                    logger.error('ffmpeg took too long')
                    # TODO handle and log

                    self.q.task_done()
                    continue

                if ffmpeg_res != 0:
                    logger.error('ffmpeg failed')
                    # TODO handle and log

                    self.q.task_done()
                    continue

                # Signal the alarm announcement if enabled in settings
                if self.alarm:
                    # TODO start later if effective is later than current time
                    out = mux_send(muxsock, 'set alarm active 1')
                    logger.info(f'Activating alarm announcement, res: {out}')

                # Perform channel replacement if enabled in settings
                if self.replace:
                    # Skip services that don't have the Alarm announcement enabled # TODO mention this in the GUI

                    # Modify the stream config in memory so all streams correspond to the alarm stream
                    for s, t, c, o in self.streams.streams:
                        service = 'srv-audio' # FIXME don't hardcode, do for each

                        # Restore the original service labels
                        label = 'NL-Alert'
                        shortlabel = label
                        pty = '3'
                        #label = self.muxcfg.services['srv-alarm']['label']
                        #shortlabel = self.muxcfg.services['srv-alarm']['shortlabel']
                        #pty = self.muxcfg.services['srv-alarm']['pty']

                        # FIXME TODO find services via component config!
                        # Replace all service labels, pty with the ones from srv-alarm
                        out = mux_send(muxsock, f'set {service} label {label},{shortlabel}')
                        logger.info(f'setting Alarm Service Label on service {service}, res: {out}')
                        out = mux_send(muxsock, f'set {service} pty {pty}')
                        logger.info(f'Setting INFO PTY on service {service}, res: {out}')

                        # Create a new config copy
                        cfg = copy.deepcopy(c)

                        cfg['input_type'] = 'file'
                        cfg['input'] = '../sub-alarm/tts.wav'

                        cfg['dls_enable'] = 'yes'
                        cfg['mot_enable'] = 'no'

                        # TODO change DLS

                        # Then, restart all modified streams with the emergency stream
                        self.streams.setcfg(s, cfg)

                self.q.task_done()
            except queue.Empty:
                pass

        muxsock.disconnect(f'ipc://{self.zmqsock}')
        self.zmq.destroy(linger=5)

    def join(self):
        if not self.is_alive():
            return

        # TODO allow the queue to be emptied first
        self._running = False
        super().join()
