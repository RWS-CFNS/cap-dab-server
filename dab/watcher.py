#
#    CFNS - Rijkswaterstaat CIV, Delft © 2021 - 2022 <cfns@rws.nl>
#
#    Copyright 2021 - 2022 Bastiaan Teeuwen <bastiaan@mkcl.nl>
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
import datetime                     # To get the current date and time
import logging                      # Logging facilities
import os                           # For file I/O
import pyttsx3                      # Text To Speech engine frontend
import queue                        # Queue for passing data to the DAB processing thread
import subprocess as subproc        # For spawning ffmpeg to convert mp3 to wav
import threading                    # Threading support (for running Mux and Mod in the background)
from cap.parser import CAPParser    # CAP XML parser (internal)
import utils

logger = logging.getLogger('server.dab')

# DAB queue watcher and message processing
# This thread handles messages received from the CAPServer
class DABWatcher(threading.Thread):
    # TODO support more languages
    TTS_MESSAGES = {
        'en-US': ('Message {num}', 'End of message {num}', 'A replay will now follow'),
        'de-DE': ('Meldung {num}', 'Ende der Meldung {num}', 'Es folgt nun eine Wiederholung'),
        'nl-NL': ('Bericht {num}', 'Einde bericht {num}', 'Er volgt nu een herhaling')
    }

    def __init__(self, config, q, zmqsock, streams, muxcfg):
        threading.Thread.__init__(self)

        self.q = q
        self.zmqsock = zmqsock
        self.streams = streams
        self.config = config
        self.muxcfg = muxcfg.cfg

        self.alarm = config['warning'].getboolean('alarm')
        self.replace = config['warning'].getboolean('replace')
        self.data = config['warning'].getboolean('data')
        self.alarmpath = f'{config["general"]["logdir"]}/streams/sub-alarm'

        # Create a fifo for data stream broadcasting
        # TODO create a temporary file in /tmp instead?
        #      this way of doing things is fine for debugging, but not for production
        self.datafifo = f'{self.alarmpath}/data.fifo'

        self.tts = pyttsx3.init()

        self._announcements = []

        self._running = True

    def _broadcast_tts(self, tts_str, language):
        # TODO create a temporary file in /tmp instead?
        #      this way of doing things is fine for debugging, but not for production
        mp3 = f'{self.alarmpath}/tts.mp3'
        wav = f'{self.alarmpath}/tts.wav'

        # Look for a voice with the right language
        voice = next((v for v in self.tts.getProperty('voices') if v.languages[0] == language), None)
        if voice is None:
            logger.error(f'Aborting TTS broadcast, {language} is not supported by the TTS backend.')
            return

        # Generate TTS output from the description
        self.tts.setProperty('voice', voice.id)
        self.tts.save_to_file(tts_str, mp3)
        self.tts.runAndWait()

        # Convert the mp3 output to wav, the format supported by odr-audioenc
        # This process also duplicates the mono channel to stereo, bitrate 48000 Hz and s16
        ffmpeg = subproc.Popen(('ffmpeg',
                                '-y',
                                '-i', mp3,
                                '-acodec', 'pcm_s16le',
                                '-ar', '48000',
                                '-ac', '2',
                                wav), stdout=subproc.DEVNULL, stderr=subproc.DEVNULL)
        try:
            if ffmpeg.wait(timeout=20) != 0:
                logger.error('Aborting TTS broadcast, ffmpeg failed')
                return
        except subproc.TimeoutExpired as e:
            logger.error('Aborting TTS broadcast, ffmpeg timed out, please report this to the developer')
            return

        # Signal the alarm announcement if enabled in settings
        if self.alarm:
            out = utils.mux_send(self.zmqsock, ('set', self.config['warning']['announcement'], 'active', '1'))
            logger.info(f'Activating alarm announcement, res: {out}')

        # Perform stream replacement if enabled in settings
        if self.replace:
            try:
                utils.replace_streams(self.zmqsock, self.config, self.muxcfg, self.streams, 'file', wav)
            except Exception as e:
                logger.error(f'Failed to perform stream replacement: {e}')
            else:
                logger.info('Replaced audio streams with alarm stream successfully')

    def run(self):
        # Maintain a list of currently active announcements
        announcements = []

        # Maintain a list of future announcements
        future_announcements = []

        # Flag that maintains whether the announcement list has been updated or not
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

        while self._running:
            try:
                # Check if there's any expired announcements to be cancelled
                for a in announcements:
                    if a['expires'] is None:
                        # Expires shouldn't be None, as the parser already check it
                        # In case it does, remove the announcement from the queue
                        logger.error(f'invalid <expires> timestamp format: {a["expires"]}')
                        announcements.remove(a)
                        changed = True
                    elif a['expires'] < datetime.datetime.now(a['expires'].tzinfo):
                        logger.info(f'Expired CAP message: {a["identifier"]}')
                        announcements.remove(a)
                        changed = True

                # Write all announcements to all data streams every second (if announcement is activated)
                # TODO think of another way of doing this
                #      perhaps less often, of only interrupting the regular data stream every minute or so
                #      Or move the entire stream replacement code to the DABData/AudioStream classes
                if self.data:
                    for s, t, c, o in self.streams.streams:
                        if c['output_type'] == 'data':
                            for a in [*announcements, *future_announcements]:
                                with open(self.datafifo, 'wb') as outfifo:
                                    # FIXME this is dangerous because it blocks
                                    outfifo.write(a['raw'])
                                    outfifo.flush()

                # Check if there's any future announcements to be activated
                for i, a in enumerate(future_announcements):
                    if a['effective'] <= datetime.datetime.now(a['effective'].tzinfo):
                        logger.info(f'Activating queued CAP message: {a["identifier"]}')
                        announcements.append(future_announcements.pop(i))
                        changed = True

                # Wait for a new CAP message from the CAPServer
                a = self.q.get(block=True, timeout=1)

                # Handle the current message
                if a['msg_type'] == CAPParser.TYPE_ALERT:
                    # Skip this message if the expiry time is before the current time
                    if a['expires'] <= datetime.datetime.now(a['expires'].tzinfo):
                        logger.warn(f'Ignoring CAP message: {a["identifier"]}, expiration date has passed')

                        self.q.task_done()
                        continue

                    # FIXME handle daylight savings properly
                    if a['effective'] <= datetime.datetime.now(a['effective'].tzinfo):
                        logger.info(f'New CAP message: {a["identifier"]}')
                        announcements.append(a)
                    else:
                        logger.info(f'New future CAP message: {a["identifier"]} for {a["effective"]}')
                        future_announcements.append(a)

                        self.q.task_done()
                        continue
                elif a['msg_type'] == CAPParser.TYPE_CANCEL:
                    cancelled = False

                    # Remove cancelled messages from the list
                    for ref in a['references']:
                        for _a in announcements:
                            if ref['sender']     == _a['sender'] and \
                               ref['identifier'] == _a['identifier'] and \
                               ref['sent']       == _a['sent']:
                                logger.info(f'Cancelled CAP message: {ref["identifier"]}')
                                announcements.remove(_a)
                                cancelled = True
                        for _a in future_announcements:
                            if ref['sender']     == _a['sender'] and \
                               ref['identifier'] == _a['identifier'] and \
                               ref['sent']       == _a['sent']:
                                logger.info(f'Cancelled CAP message: {ref["identifier"]}')
                                future_announcements.remove(_a)
                                cancelled = True

                    # Prevent restarting the stream(s) if no message was cancelled
                    if cancelled == False:
                        logger.warn(f'Invalid CAP cancel request: {ref["identifier"]} {ref["sender"]} {ref["sent"]}')

                        self.q.task_done()
                        continue

                changed = True
                self.q.task_done()
            except queue.Empty:
                if not changed:
                    continue

            if not self._running:
                break
            changed = False

            if len(announcements) == 0:
                # Stop the alarm announcement and switch services back to their original streams
                for s, t, c, o in self.streams.streams:
                    if c['output_type'] != 'data':
                        if self.alarm:
                            out = utils.mux_send(self.zmqsock, ('set', 'alarm', 'active', '0'))
                            logger.info(f'Alarm announcement deactivated, res: {out}')

                        if self.replace:
                            try:
                                utils.replace_streams(self.zmqsock, self.config, self.muxcfg, self.streams)
                                logger.info('Original audio streams restored successfully')
                            except Exception as e:
                                logger.error(f'Failed to restore original audio stream: {e}')
                    elif self.data:
                        utils.replace_streams(self.zmqsock, self.config, self.muxcfg, self.streams, None, None, data_streams=True)
                        logger.info('Original data streams restored successfully')
            elif self.alarm or self.replace:
                # Check if there's audio (alarm announcement and stream replacement) streams to be processed
                # FIXME do pythonic way, this is lazy
                audiostreams = datastreams = 0
                for s, t, c, o in self.streams.streams:
                    if c['output_type'] != 'data':
                        audiostreams += 1
                    else:
                        datastreams += 1

                # Replace data streams with a custom stream of warnings
                if datastreams > 0:
                    try:
                        utils.replace_streams(self.zmqsock, self.config, self.muxcfg, self.streams, 'fifo', self.datafifo, True)
                    except Exception as e:
                        logger.error(f'Failed to perform stream replacement: {e}')
                    else:
                        logger.info('Replaced data streams with alarm stream successfully')

                # Start audio stream announcements
                if audiostreams > 0:
                    logger.info(f'Preparing TTS message...')
                    # Generate the TTS input
                    tts_str = ''
                    lang = announcements[0]['lang']

                    # FIXME english is broken on macOS, cuts off halfway
                    if lang not in self.TTS_MESSAGES.keys():
                        lang = 'en-US'

                    if len(announcements) == 1:
                        tts_str += f'{_slnc(2000)} {announcements[0]["description"]}. {_slnc(500)}'
                        tts_str += self.TTS_MESSAGES[lang][1].format(num='')
                    else:
                        # In the case there's multiple messages in the queue:
                        # Combine them into a single string with start and end markers.
                        for i, a in enumerate(announcements):
                            #lang = a['lang'] # FIXME mixed languages
                            tts_str += '{s1} {opening}. {s2} {msg}. {s3} {closing}. '.format(
                                        s1      = _slnc(2000),
                                        opening = self.TTS_MESSAGES[lang][0].format(num=i + 1),
                                        s2      = _slnc(1000),
                                        msg     = a['description'],
                                        s3      = _slnc(500),
                                        closing = self.TTS_MESSAGES[lang][1].format(num=i + 1)
                                       )
                    tts_str += _slnc(2000) + self.TTS_MESSAGES[lang][2]

                    # Broadcast our message on all channels with alarm announcement enabled
                    self._broadcast_tts(tts_str, lang.replace('-', '_'))

    def join(self):
        if not self.is_alive():
            return

        # TODO allow the queue to be emptied first
        self._running = False
        super().join()
