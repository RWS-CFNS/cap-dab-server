from dab.odr import *                       # OpenDigitalRadio server support
#from dab.fraunhofer import ContentServer   # TODO Fraunhofer ContentServer support
import subprocess                           # For state of ODR-DabMux and ODR-DabMod
import time                                 # For sleep support

logger = logging.getLogger('server.dab')

class DABServer():
    def __init__(self, config, q):
        self._srvcfg = config
        self._q = q

        self._odr = None
        self._watcher = None
        self.config = None

    def start(self):
        logger.info('Starting up DAB ensemble...')

        # Load ODR-DabMux configuration into memory
        self.config = ODRMuxConfig(self._srvcfg['dab']['telnetport'])
        if not self.config.load(self._srvcfg['dab']['mux_config']):
            logger.error(f'Unable to load DAB multiplexer configuration: {muxcfg}')
            return False

        # Start the DABServer thread
        try:
            self._odr = ODRServer(self._srvcfg)
            self._odr.start()
        except KeyError as e:
            logger.error(f'Unable to start DAB server thread, check configuration. {e}')
            return False
        except Exception as e:
            logger.error(f'Unable to start DAB server thread. {e}')
            return False

        # TODO check if multiplexer and modulator were successfully started

        # Start a watcher thread to process messages from the CAPServer
        try:
            self._watcher = DABWatcher(self._srvcfg, self._q)
            self._watcher.start()
        except KeyError as e:
            logger.error(f'Unable to start DAB watcher thread, check configuration. {e}')
            return False
        except OSError as e:
            logger.error(f'Unable to start DAB watcher thread. Invalid streams config. {e}')
            return False
        except Exception as e:
            logger.error(f'Unable to start DAB watcher thread. {e}')
            return False

        return True

    def stop(self):
        if self.config == None:
            return

        if self._odr != None:
            self._odr.join()
        if self._watcher != None:
            self._watcher.join()

    def restart(self):
        if self.config == None:
            return False

        # Save changes made to the multiplexer config
        self.config.write()

        # Shutdown all DAB threads
        self.stop()

        # Allow sockets some time to unbind
        time.sleep(4)

        # Start the server back up
        return self.start()

    # Return the status of the (DAB Server, DAB watcher, DAB Multiplexer, DAB MOdulator)
    def status(self):
        if self.config == None:
            return (False, False, False, False)

        server = self._odr.is_alive()
        watcher = self._watcher.is_alive()
        # FIXME check these properly
        mux = subprocess.run(('pgrep', 'odr-dabmux'), capture_output=True).returncode == 0
        mod = subprocess.run(('pgrep', 'odr-dabmod'), capture_output=True).returncode == 0

        return (server, watcher, mux, mod)
