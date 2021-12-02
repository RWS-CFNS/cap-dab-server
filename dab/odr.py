import threading                                    # Threading support (for running Mux and Mod in the background)
import signal                                       # For sending a signal to terminate subprocesses
import os                                           # For sending a signal to terminate subprocesses
import subprocess as subproc                        # Support for starting subprocesses
from dab.boost_info_parser import BoostInfoParser   # C++ Boost INFO format parser (used for dabmux.cfg)

#class CAPServer(threading.Thread):
#    def __init__(self, app, host, port):
#        threading.Thread.__init__(self)
#
#        self.server = make_server(host, port, app)
#        self.ctx = app.app_context()
#        self.ctx.push()
#
#    def run(self):
#        self.server.serve_forever()
#
#    def join(self):
#        self.server.shutdown()


class ODRServer(threading.Thread):
    def __init__(self, logdir, muxcfg, modcfg):
        threading.Thread.__init__(self)

        self.logdir = logdir
        self.muxcfg = muxcfg
        self.modcfg = modcfg

        self.muxpid = None
        self.modpid = None

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

        mux.stdout.close()
        out = mod.communicate()[0]

        modlog.close()
        muxlog.close()

        # FIXME this don't work properly, make sure odr-dabmux en odr-dabmod exit properly before the program is
        # closed
        #mux.kill()
        #mod.kill()

        #sp.run('bin/odr-dabmux cfg/dabmux.cfg'
        # TODO check if process fails

    def join(self):
        if self.mux:
            print('Waiting for DAB multiplexer to terminate... ', end='')
            self.mux.terminate()
            if self.mux.poll() is None:
                print('OK')
            else:
                print('FAIL')

        if self.mod:
            print('Waiting for DAB modulator to terminate... ', end='')
            self.mod.terminate()
            if self.mod.poll() is None:
                print('OK')
            else:
                print('FAIL')

        #os.killpg(os.getpgid(self.muxpid, signal.SIGTERM))
        #os.killpg(os.getpgid(self.modpid, signal.SIGTERM))
