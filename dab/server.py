from dab.odr import ODRServer               # OpenDigitalRadio server support
#from dab.fraunhofer import FraunhoferServer # TODO Fraunhofer ContentServer support

def dab_server(logdir, muxcfg, modcfg):
    print('Starting up DAB ensemble...')
    server = ODRServer(logdir, muxcfg, modcfg)
    server.start()

    return server
