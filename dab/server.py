from dab.odr import ODRServer               # OpenDigitalRadio server support
#from dab.fraunhofer import FraunhoferServer # TODO Fraunhofer ContentServer support

def dab_server(logdir):
    srv = ODRServer(logdir)

    srv.start()

