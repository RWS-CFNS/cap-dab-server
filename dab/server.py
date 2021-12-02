from dab.odr import *                     # OpenDigitalRadio server support
#from dab.fraunhofer import ContentServer # TODO Fraunhofer ContentServer support

class DABServer():
    def __init__(logdir, muxcfg, modcfg):
        self.logdir = logdir
        self.muxcfg = muxcfg
        self.modcfg = modcfg

    def start():
        print('Starting up DAB ensemble...')
        server = ODRServer(logdir, muxcfg, modcfg)
        server.start()

    def muxstate():
        return True

    def modstate():
        return True

def dab_server(logdir, muxcfg, modcfg):
    print('Starting up DAB ensemble...')
    server = ODRServer(logdir, muxcfg, modcfg)
    server.start()

    cfg = odr_mux_config(muxcfg)

    return (server, cfg)
