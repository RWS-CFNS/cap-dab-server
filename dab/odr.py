import subprocess as subproc

class ODRServer:
    def __init__(self, logdir):
        self.logdir = logdir

    def start(self):
        with open(f'{self.logdir}/dabmux.log', 'ab') as muxlog, open(f'{self.logdir}/dabmod.log', 'ab') as modlog:
            # Start up odr-dabmux DAB multiplexer
            muxlog.write('\n'.encode('utf-8'))
            mux = subproc.Popen(('bin/odr-dabmux', 'cfg/dabmux.cfg'),
                    stdout=subproc.PIPE, stderr=muxlog)

            # Start up odr-dabmod DAB modulator
            modlog.write('\n'.encode('utf-8'))
            #mod = subproc.Popen(('bin/odr-dabmod', 'cfg/dabmod.ini'),
            mod = subproc.Popen(('bin/odr-dabmod', '-f', '/tmp/welle-io.fifo', '-m', '1', '-F', 'u8'),
                        stdin=mux.stdout, stdout=subproc.PIPE, stderr=modlog)
            mux.stdout.close()
            out = mod.communicate()[0]

            # FIXME this don't work properly, make sure odr-dabmux en odr-dabmod exit properly before the program is
            # closed
            mux.kill()
            mod.kill()

        #sp.run('bin/odr-dabmux cfg/dabmux.cfg'
        # TODO check if process fails
