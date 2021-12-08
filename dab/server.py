from dab.odr import *                     # OpenDigitalRadio server support
#from dab.fraunhofer import ContentServer # TODO Fraunhofer ContentServer support

logger = logging.getLogger('server.dab')

def dab_server(q, config):
    logger.info('Starting up DAB ensemble...')

    # Load ODR-DabMux configuration into memory
    cfg = ODRMuxConfig(config['dab']['telnetport'])
    if not cfg.load(config['dab']['mux_config']):
        logger.error(f'Invalid file: {muxcfg}. Unable to start DAB server')
        return (None, None, None)

    # Create a watcher thread to process messages from the CAPServer
    stream_config = config['dab']['stream_config']
    watcher = DABWatcher(q, stream_config, config['dab']['telnetport'])
    if watcher == None:
        logger.error(f'Invalid file: {stream_config}. Unable to start DAB watcher thread')
        return (None, None, None)

    # Create the DABServer thread
    server = ODRServer(config['general']['logdir'], config['dab']['mux_config'], config['dab']['mod_config'])

    # Start all threads
    server.start()
    watcher.start()

    return (server, watcher, cfg)
