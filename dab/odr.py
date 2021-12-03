import os                                                           # For checking if files exist
import logging                                                      # Logging facilities
import threading                                                    # Threading support (for running Mux and Mod in the background)
import subprocess as subproc                                        # Support for starting subprocesses
from dab.boost_info_parser import BoostInfoTree, BoostInfoParser    # C++ Boost INFO format parser (used for dabmux.cfg)

logger = logging.getLogger('server.dab')

# OpenDigitalRadio DAB Multiplexer and Modulator support
class ODRServer(threading.Thread):
    def __init__(self, logdir, muxcfg, modcfg):
        threading.Thread.__init__(self)

        self.logdir = logdir
        self.muxcfg = muxcfg
        self.modcfg = modcfg

    def run(self):
        muxlog = open(f'{self.logdir}/dabmux.log', 'ab')
        modlog = open(f'{self.logdir}/dabmod.log', 'ab')

        # Start up odr-dabmux DAB multiplexer
        muxlog.write('\n'.encode('utf-8'))
        mux = subproc.Popen(('bin/odr-dabmux', self.muxcfg), stdout=subproc.PIPE, stderr=muxlog)
        self.mux = mux

        # Start up odr-dabmod DAB modulator
        modlog.write('\n'.encode('utf-8'))
        #mod = subproc.Popen(('bin/odr-dabmod', self.modcfg), stdin=mux.stdout, stdout=subproc.PIPE, stderr=modlog)
        mod = subproc.Popen(('bin/odr-dabmod', '-f', '/tmp/welle-io.fifo', '-m', '1', '-F', 'u8'),
                    stdin=mux.stdout, stdout=subproc.PIPE, stderr=modlog)
        self.mod = mod

        # Allow odr-dabmux to receive SIGPIPE if odr-dabmod exits
        mux.stdout.close()
        # Send odr-dabmux's data to odr-dabmod. This operation blocks until the process in killed
        out = mod.communicate()[0]

        modlog.close()
        muxlog.close()

    def join(self):
        if self.mod != None:
            logger.info('Waiting for DAB modulator to terminate...')
            self.mod.terminate()
            if self.mod.poll() is None:
                logger.info('DAB modulator terminated successfully!')
            else:
                logger.error('Terminating DAB modulator failed. Attempt quitting manually.')

        if self.mux != None:
            logger.info('Waiting for DAB multiplexer to terminate...')
            self.mux.terminate()
            if self.mux.poll() is None:
                logger.info('DAB modulator terminated successfully!')
            else:
                logger.error('Terminating DAB multiplexer failed. Attempt quitting manually.')

class ODRMuxConfig():
    def __init__(self):
        self.p = BoostInfoParser()

    def load(self, cfgfile):
        if cfgfile == None:
            return None

        self.file = cfgfile

        # attempt to read the file
        if cfgfile != None and os.path.isfile(cfgfile):
            self.p.read(cfgfile)
            self.cfg = self.p.getRoot()
            return self.cfg

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

        # TODO set this randomly at runtime, even when loading file
        #cfg.remotecontrol['telnetport'] = '10000'
        #cfg.remotecontrol['zmqendpoint'] = 'tcp://lo:10000'

        self.cfg.ensemble['id'] = '0x8FFF'               # Default to The Netherlands
        self.cfg.ensemble['ecc'] = '0xE3'
        self.cfg.ensemble['local-time-offset'] = 'auto'
        self.cfg.ensemble['international-table'] = '1'
        self.cfg.ensemble['reconfig-counter'] = 'hash'   # Enable FIG 0/7
        self.cfg.ensemble['label'] = 'DAB Ensemble'      # Set a generic default name
        self.cfg.ensemble['shortlabel'] = 'DAB'

        #root.services
        #root.subchannels
        #root.components

        self.cfg.outputs['stdout'] = 'fifo:///dev/stdout?type=raw'

        return self.cfg

    def write(self):
        self.p.write(self.file)
