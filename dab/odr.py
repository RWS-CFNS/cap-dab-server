import threading                                    # Threading support (for running Mux and Mod in the background)
import subprocess as subproc                        # Support for starting subprocesses
from dab.boost_info_parser import BoostInfoParser   # C++ Boost INFO format parser (used for dabmux.cfg)

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
        if self.mod:
            print('Waiting for DAB modulator to terminate... ', end='', flush=True)
            self.mod.terminate()
            if self.mod.poll() is None:
                print('OK')
            else:
                print('FAIL')

        if self.mux:
            print('Waiting for DAB multiplexer to terminate... ', end='', flush=True)
            self.mux.terminate()
            if self.mux.poll() is None:
                print('OK')
            else:
                print('FAIL')

class ODRMuxConfig():
    def __init__(self):
        pass

#class ODRModConfig():
