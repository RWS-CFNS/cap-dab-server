from dab.odr import *                     # OpenDigitalRadio server support
#from dab.fraunhofer import ContentServer # TODO Fraunhofer ContentServer support

logger = logging.getLogger('server.dab')

class DABServer():
    def __init__(logdir, muxcfg, modcfg):
        self.logdir = logdir
        self.muxcfg = muxcfg
        self.modcfg = modcfg

    def start():
        logger.info('Starting up DAB ensemble...')
        server = ODRServer(logdir, muxcfg, modcfg)
        server.start()

    def muxstate():
        return True

    def modstate():
        return True

def dab_server(logdir, muxcfg, modcfg):
    logger.info('Starting up DAB ensemble...')

    odrmuxcfg = ODRMuxConfig()
    cfg = odrmuxcfg.load(muxcfg)
    if cfg == None:
        logger.error(f'Invalid file: {muxcfg}. Unable to start DAB server')
        return (None, None)

    server = ODRServer(logdir, muxcfg, modcfg)
    server.start()

    return (server, cfg)
