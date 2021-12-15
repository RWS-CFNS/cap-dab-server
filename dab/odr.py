import configparser                                                 # Python INI file parser
import copy                                                         # For saving/restoring Config objects
import os                                                           # For file I/O
import stat                                                         # For checking if output is a FIFO
import logging                                                      # Logging facilities
import queue                                                        # Queue for passing data to the DAB processing thread
import subprocess as subproc                                        # Support for starting subprocesses
import telnetlib                                                    # For signalling (alarm) announcements from DABWatcher
import threading                                                    # Threading support (for running Mux and Mod in the background)
from dab.boost_info_parser import BoostInfoTree, BoostInfoParser    # C++ Boost INFO format parser (used for dabmux.cfg)

logger = logging.getLogger('server.dab')

# DAB queue watcher and message processing
# This thread handles messages received from the CAPServer
class DABWatcher(threading.Thread):
    def __init__(self, config, q):
        threading.Thread.__init__(self)

        self.telnetport = int(config['dab']['telnetport'])
        self.alarm = config['warning'].getboolean('alarm')
        self.replace = config['warning'].getboolean('replace')

        self.q = q

        # Load in streams.ini
        stream_config = config['dab']['stream_config']
        os.makedirs(os.path.dirname(stream_config), exist_ok=True)
        self.config = configparser.ConfigParser()
        if os.path.isfile(stream_config):
            self.config.read(stream_config)
        else:
            logger.error(f'Invalid file: {stream_config}. Unable to start DAB watcher thread')
            raise OSError.FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), stream_config)

        #with open(stream_config, 'w') as config_file:
            #config.write(config_file)

        self._running = True

    def run(self):
        # main a list of currently active announcements with their expiry date
        announcements = []

        while self._running:
            try:
                # Wait for a message from the CAPServer
                lang, effective, expires, description = self.q.get(block=True, timeout=4)
                logger.info(lang + effective + expires + description)

                if self.alarm:
                    # signal the alarm announcement
                    # TODO start later if effective is later than current time
                    with telnetlib.Telnet('localhost', self.telnetport) as t:
                        t.write(b'set alarm active 1\n')

                if self.replace:
                    #replace all streams with the one from sub-alarm
                    #replace all service labels, pty with the ones from srv-alarm
                    pass
            except queue.Empty:
                pass

    def join(self):
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

        root.services['srv-alarm']['id'] = '0x8AAA'
        root.services['srv-alarm']['label'] = 'Alarm announcement'
        root.services['srv-alarm']['shortlabel'] = 'Alarm'
        root.services['srv-alarm']['pty'] = '3'
        root.services['srv-alarm']['pty-sd'] = 'static'
        root.services['srv-alarm']['announcements']['Alarm'] = 'true'
        root.services['srv-alarm']['announcements']['clusters'] = '1'

        # FIXME generate subchannel on the fly based on streams.ini
        root.subchannels['sub-alarm']['type'] = 'dabplus'
        root.subchannels['sub-alarm']['bitrate'] = '96'
        root.subchannels['sub-alarm']['id'] = '1'
        root.subchannels['sub-alarm']['protection-profile'] = 'EEP_A'
        root.subchannels['sub-alarm']['protection'] = '3'
        root.subchannels['sub-alarm']['inputproto'] = 'zmq'
        root.subchannels['sub-alarm']['inputuri'] = 'tcp://*:39801'
        root.subchannels['sub-alarm']['zmq-buffer'] = '40'
        root.subchannels['sub-alarm']['zmq-prebuffering'] = '20'

        root.components['comp-alarm']['type'] = '2'                                 # Type 2 = multi-channel
        root.components['comp-alarm']['service'] = 'srv-alarm'
        root.components['comp-alarm']['subchannel'] = 'sub-alarm'
        root.components['comp-alarm']['user-applications']['userapp'] = 'slideshow' # Enable MOT slideshow

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
