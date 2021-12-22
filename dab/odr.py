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

import configparser                                                 # Python INI file parser
import copy                                                         # For saving/restoring Config objects
import os                                                           # For file I/O
import stat                                                         # For checking if output is a FIFO
import logging                                                      # Logging facilities
import pyttsx3                                                      # Text To Speech engine frontend
import queue                                                        # Queue for passing data to the DAB processing thread
import subprocess as subproc                                        # Support for starting subprocesses
import telnetlib                                                    # For signalling (alarm) announcements from DABWatcher
import threading                                                    # Threading support (for running Mux and Mod in the background)
from dab.boost_info_parser import BoostInfoTree, BoostInfoParser    # C++ Boost INFO format parser (used for dabmux.cfg)

logger = logging.getLogger('server.dab')

# DAB queue watcher and message processing
# This thread handles messages received from the CAPServer
class DABWatcher(threading.Thread):
    def __init__(self, config, q, streams):
        threading.Thread.__init__(self)

        self.telnetport = int(config['dab']['telnetport'])
        self.alarm = config['warning'].getboolean('alarm')
        self.replace = config['warning'].getboolean('replace')

        self.alarmpath = f'{config["general"]["logdir"]}/streams/sub-alarm'

        self.q = q
        self.streams = streams

        # Load in streams.ini
        stream_config = config['dab']['stream_config']
        os.makedirs(os.path.dirname(stream_config), exist_ok=True)
        self.streamscfg = configparser.ConfigParser()
        if os.path.isfile(stream_config):
            self.streamscfg.read(stream_config)
        else:
            logger.error(f'Invalid file: {stream_config}. Unable to start DAB watcher thread')
            raise OSError.FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), stream_config)

        self.tts = pyttsx3.init()

        self._running = True

    def run(self):
        # Main a list of currently active announcements with their expiry date
        announcements = []

        while self._running:
            try:
                # Wait for a message from the CAPServer
                lang, effective, expires, description = self.q.get(block=True, timeout=2)
                logger.info(f'CAP message: lang - effective - expires - description') # TODO put in CAPServer

                # Generate TTS output from the description
                mp3 = f'{self.alarmpath}/tts.mp3'
                # TODO look for the right language
                self.tts.setProperty('voice', 'com.apple.speech.synthesis.voice.xander')
                self.tts.save_to_file(description, mp3)
                self.tts.runAndWait()

                # Convert the mp3 output to wav, the format supported by odr-audioenc
                # This process also duplicates the mono channel to stereo, bitrate 48000 Hz and s16
                # FIXME handle conditions where the conversion fails
                # TODO output log somewhere
                ffmpeg = subproc.Popen(( 'ffmpeg',
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
                    continue

                if ffmpeg_res != 0:
                    logger.error('ffmpeg failed')
                    # TODO handle and log
                    continue

                if self.alarm:
                    # Signal the alarm announcement
                    # TODO start later if effective is later than current time
                    with telnetlib.Telnet('localhost', self.telnetport) as t:
                        t.write(b'set alarm active 1\n')

                if self.replace:
                    # Skip services that don't have the Alarm announcement enabled # TODO mention this in the GUI

                    # Modify the stream config in memory so all streams correspond to the alarm stream
                    for stream in self.streamscfg.sections():
                        self.streamscfg[stream]['input_type'] = 'file'
                        self.streamscfg[stream]['input'] = '../sub-alarm/tts.wav'

                        self.streamscfg[stream]['dls_enable'] = 'yes'
                        self.streamscfg[stream]['mot_enable'] = 'no'

                        # FIXME find services via component config!
                        with telnetlib.Telnet('localhost', self.telnetport) as t:
                            t.write(b'set srv-audio label NL-Alert,NL-Alert\n')
                            t.write(b'set srv-audio pty 3\n')

                        # Then, restart all modified streams
                        self.streams.chreplace(stream, self.streamscfg[stream])

                    #replace all streams with the one from sub-alarm
                    #replace all service labels, pty with the ones from srv-alarm
                    pass
            except queue.Empty:
                pass

    def join(self):
        if not self.is_alive():
            return

        # TODO allow the queue to be emptied first
        self._running = False
        self.q.join()
        super().join()

# OpenDigitalRadio DAB Multiplexer and Modulator support
class ODRServer(threading.Thread):
    def __init__(self, config):
        threading.Thread.__init__(self)

        self.logdir = config['general']['logdir']
        self.binpath = config['dab']['odrbin_path']
        self.muxcfg = config['dab']['mux_config']
        self.modcfg = config['dab']['mod_config']
        self.output = config['dab']['output']

        self.mux = None
        self.mod = None

        # Check if ODR-DabMux and ODR-DabMod are available
        muxbin = f'{self.binpath}/odr-dabmux'
        if not os.path.isfile(muxbin):
            raise Exception(f'Invalid path to DAB Multiplexer binary: {muxbin}')

        modbin = f'{self.binpath}/odr-dabmod'
        if not os.path.isfile(modbin):
            raise Exception(f'Invalid path to DAB Modulator binary: {modbin}')

        if os.name == 'posix':
            if not os.access(muxbin, os.X_OK):
                raise Exception(f'DAB Multiplexer binary not executable: {muxbin}')
            if not os.access(modbin, os.X_OK):
                raise Exception(f'DAB Modulator binary not executable: {modbin}')

    def run(self):
        # TODO rotate this log, this is not so straightforward it appears
        muxlog = open(f'{self.logdir}/dabmux.log', 'ab')
        modlog = open(f'{self.logdir}/dabmod.log', 'ab')

        # check if there's already a file with the same name as our output
        if os.path.exists(self.output):
            # if this is a fifo, we don't need to take any action
            if not stat.S_ISFIFO(os.stat(self.output).st_mode):
                # otherwise delete the file/dir
                if os.path.isfile(self.output):
                    os.remove(self.output)
                elif os.path.isdir(self.output):
                    os.rmdir(self.output)
                else:
                    raise Exception(f'Unable to remove already existing output path: {self.output}')

                # Create the FIFO that odr-dabmod outputs to
                os.mkfifo(self.output)
        else:
            # Create the FIFO that odr-dabmod outputs to
            os.mkfifo(self.output)

        # Start up odr-dabmux DAB multiplexer
        muxlog.write('\n'.encode('utf-8'))
        self.mux = subproc.Popen((f'{self.binpath}/odr-dabmux', self.muxcfg), stdout=subproc.PIPE, stderr=muxlog)

        # Start up odr-dabmod DAB modulator
        modlog.write('\n'.encode('utf-8'))
        # TODO load dabmod config (perhaps by option) / allow manually passing cmdline to odr-dabmod
        #mod = subproc.Popen(('bin/odr-dabmod', self.modcfg), stdin=mux.stdout, stdout=subproc.PIPE, stderr=modlog)
        self.mod = subproc.Popen((f'{self.binpath}/odr-dabmod', '-f', self.output, '-m', '1', '-F', 'u8'),
                                 stdin=self.mux.stdout, stdout=subproc.PIPE, stderr=modlog)

        # Allow odr-dabmux to receive SIGPIPE if odr-dabmod exits
        self.mux.stdout.close()
        # Send odr-dabmux's data to odr-dabmod. This operation blocks until the process in killed
        self.mod.communicate()[0]

        modlog.close()
        muxlog.close()

    def join(self):
        if not self.is_alive():
            return

        # Terminate the modulator and multiplexer
        if self.mod != None:
            self.mod.terminate()
            if self.mod.poll() is None:
                logger.info('DAB modulator terminated successfully!')
            else:
                logger.error('Terminating DAB modulator failed. Attempt quitting manually.')

        if self.mux != None:
            self.mux.terminate()
            if self.mux.poll() is None:
                logger.info('DAB modulator terminated successfully!')
            else:
                logger.error('Terminating DAB multiplexer failed. Attempt quitting manually.')

        # Remove the fifo file that was used as output
        os.remove(self.output)

        super().join()

# ODR-DabMux config file wrapper class
class ODRMuxConfig():
    def __init__(self, telnetport):
        self.p = BoostInfoParser()
        self.telnetport = telnetport

        self.oldcfg = None

    def load(self, cfgfile):
        if cfgfile == None:
            return False

        self.file = cfgfile

        # attempt to read the file
        if cfgfile != None and os.path.isfile(cfgfile):
            self.p.read(cfgfile)
            self.cfg = self.p.getRoot()

            # overwrite the default telnetport with the port specified in the server settings file
            self.cfg.remotecontrol['telnetport'] = str(self.telnetport)
            self.write()

            return True

        logger.warning(f'Unable to read {cfgfile}, creating a new config file')

        # generate a new config file otherwise
        self.cfg = BoostInfoTree()

        # load in defaults, refer to:
        # - https://github.com/Opendigitalradio/ODR-DabMux/blob/master/doc/example.mux
        # - https://github.com/Opendigitalradio/ODR-DabMux/blob/master/doc/advanced.mux

        self.cfg.general['dabmode'] = '1'               # DAB Transmission mode (https://en.wikipedia.org/wiki/Digital_Audio_Broadcasting#Bands_and_modes)
        self.cfg.general['nbframes'] = '0'              # Don't limit the number of ETI frames generated
        self.cfg.general['syslog'] = 'false'
        self.cfg.general['tist'] = 'false'              # Disable downloading leap second information
        self.cfg.general['managementport'] = '0'        # Disable management port

        self.cfg.remotecontrol['telnetport'] = str(self.telnetport)

        self.cfg.ensemble['id'] = '0x8FFF'               # Default to The Netherlands
        self.cfg.ensemble['ecc'] = '0xE3'
        self.cfg.ensemble['local-time-offset'] = 'auto'
        self.cfg.ensemble['international-table'] = '1'
        self.cfg.ensemble['reconfig-counter'] = 'hash'   # Enable FIG 0/7
        self.cfg.ensemble['label'] = 'DAB Ensemble'      # Set a generic default name
        self.cfg.ensemble['shortlabel'] = 'DAB'

        #root.services
        # Create a default Pseudo alarm announcement subchannel
        #  This sub-channel is an integral part of the PoC and aims to support warning messages on devices that don't
        #  support DAB-EWF or even the DAB Alarm Announcement.
        self.cfg.ensemble.announcements.alarm['cluster']
        self.cfg.ensemble.announcements.alarm.flags['Alarm'] = 'true'
        self.cfg.ensemble.announcements.alarm['subchannel'] = 'sub-alarm'

        self.cfg.services['srv-alarm']['id'] = '0x8AAA'
        self.cfg.services['srv-alarm']['label'] = 'Alarm announcement'
        self.cfg.services['srv-alarm']['shortlabel'] = 'Alarm'
        self.cfg.services['srv-alarm']['pty'] = '3'
        self.cfg.services['srv-alarm']['pty-sd'] = 'static'
        self.cfg.services['srv-alarm']['announcements']['Alarm'] = 'true'
        self.cfg.services['srv-alarm']['announcements']['clusters'] = '1'

        # FIXME generate subchannel on the fly based on streams.ini
        self.cfg.subchannels['sub-alarm']['type'] = 'dabplus'
        self.cfg.subchannels['sub-alarm']['bitrate'] = '96'
        self.cfg.subchannels['sub-alarm']['id'] = '1'
        self.cfg.subchannels['sub-alarm']['protection-profile'] = 'EEP_A'
        self.cfg.subchannels['sub-alarm']['protection'] = '3'
        self.cfg.subchannels['sub-alarm']['inputproto'] = 'zmq'
        self.cfg.subchannels['sub-alarm']['inputuri'] = 'tcp://*:39801'
        self.cfg.subchannels['sub-alarm']['zmq-buffer'] = '40'
        self.cfg.subchannels['sub-alarm']['zmq-prebuffering'] = '20'

        self.cfg.components['comp-alarm']['type'] = '2'                                 # Type 2 = multi-channel
        self.cfg.components['comp-alarm']['service'] = 'srv-alarm'
        self.cfg.components['comp-alarm']['subchannel'] = 'sub-alarm'
        self.cfg.components['comp-alarm']['user-applications']['userapp'] = 'slideshow' # Enable MOT slideshow

        # Output to stdout because we'll be piping the output into ODR-DabMux
        self.cfg.outputs['stdout'] = 'fifo:///dev/stdout?type=raw'

        self.write()

        return True

    def save(self):
        self.oldcfg = copy.deepcopy(self.cfg)

    def restore(self):
        if self.oldcfg == None:
            return

        self.cfg = self.oldcfg
        self.oldcfg = None

    def write(self):
        self.p.load(self.cfg)
        self.p.write(self.file)
