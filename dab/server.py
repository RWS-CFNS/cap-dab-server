#
#    CFNS - Rijkswaterstaat CIV, Delft © 2021 - 2022 <cfns@rws.nl>
#
#    Copyright 2021 - 2022 Bastiaan Teeuwen <bastiaan@mkcl.nl>
#
#    This file is part of cap-dab-server
#
#    cap-dab-server is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    cap-dab-server is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with cap-dab-server. If not, see <https://www.gnu.org/licenses/>.
#

import atexit                       # For cleaning up ZMQ context upon garbage collection
import configparser                 # Python INI file parser
import os                           # For file I/O
import logging                      # Logging facilities
import queue                        # Queue for passing data to the DAB processing thread
import subprocess as subproc        # Support for starting subprocesses
import threading                    # Threading support (for running odr-dabmux and odr-dabmod in the background)
import time                         # For sleep support
import zmq                          # For signalling (alarm) announcements to ODR-DabMux
from dab.muxcfg import ODRMuxConfig # odr-dabmux config
from dab.streams import DABStreams	# DAB streams manager
from dab.watcher import DABWatcher  # DAB CAP message watcher
import utils

logger = logging.getLogger('server.dab')

# OpenDigitalRadio DAB Multiplexer and Modulator support
class ODRServer(threading.Thread):
    def __init__(self, config):
        threading.Thread.__init__(self)

        self.logdir = config['general']['logdir']
        self.binpath = config['dab']['odrbin_path']
        self.muxcfg = config['dab']['mux_config']
        self.modcfg = config['dab']['mod_config']
        self.output = '/tmp/welle-io.fifo'           # FIXME FIXME FIXME FIXME get from dabmod.ini (filename)

        self.mux = None
        self.mod = None

        # Check if ODR-DabMux and ODR-DabMod are available
        muxbin = f'{self.binpath}/odr-dabmux'
        if not os.path.isfile(muxbin):
            raise Exception(f'Invalid path to DAB Multiplexer binary: {muxbin}')

        modbin = f'{self.binpath}/odr-dabmod'
        if not os.path.isfile(modbin):
            raise Exception(f'Invalid path to DAB Modulator binary: {modbin}')

        if os.name == 'posix':
            if not os.access(muxbin, os.X_OK):
                raise Exception(f'DAB Multiplexer binary not executable: {muxbin}')
            if not os.access(modbin, os.X_OK):
                raise Exception(f'DAB Modulator binary not executable: {modbin}')

        self._running = True

    def run(self):
        # TODO rotate this log, this is not so straightforward it appears
        muxlog = open(f'{self.logdir}/dabmux.log', 'ab')
        modlog = open(f'{self.logdir}/dabmod.log', 'ab')

        # Create the FIFO that odr-dabmod outputs to
        utils.create_fifo(self.output)

        failcounter = 0
        while self._running and failcounter < 4:
            # Start up odr-dabmux DAB multiplexer
            muxlog.write('\n'.encode('utf-8'))
            self.mux = subproc.Popen((f'{self.binpath}/odr-dabmux', self.muxcfg), stdout=subproc.PIPE, stderr=muxlog)

            # Start up odr-dabmod DAB modulator
            modlog.write('\n'.encode('utf-8'))
            self.mod = subproc.Popen((f'{self.binpath}/odr-dabmod', self.modcfg),
                                    stdin=self.mux.stdout, stdout=subproc.PIPE, stderr=modlog)

            # Allow odr-dabmux to receive SIGPIPE if odr-dabmod exits
            self.mux.stdout.close()
            # Send odr-dabmux's data to odr-dabmod. This operation blocks until the process in killed
            self.mod.communicate()[0]

            # Wait 4 seconds for sockets to unbind
            time.sleep(4)

            # Maintain a failcounter to automatically exit the loop if we are unable to bring the server up
            failcounter += 1

        if self._running:
            logger.error(f'Terminating DAB server. odr-dabmux and/or odr-dabmod failed to start {failcounter} times')

        modlog.close()
        muxlog.close()

    def join(self):
        if not self.is_alive():
            return

        self._running = False

        # Terminate the modulator and multiplexer
        if self.mod is not None:
            self.mod.terminate()
            try:
                self.mod.wait(timeout=5)
            except subproc.TimeoutExpired as e:
                logger.error(f'Unable to terminate odr-dabmod. {e}')

        if self.mux is not None:
            self.mux.terminate()
            try:
                self.mux.wait(timeout=5)
            except subproc.TimeoutExpired as e:
                logger.error(f'Unable to terminate odr-dabmux. {e}')

        # Remove the fifo file that was used as output
        os.remove(self.output)

        super().join()

class DABServer():
    def __init__(self, config: configparser.ConfigParser, q: queue.Queue, streams: DABStreams):
        self._srvcfg = config
        self._q = q
        self._streams = streams

        self._odr = None
        self._watcher = None
        self.config = None

        self._zmq = zmq.Context()
        self.zmqsock = None

        atexit.register(self.deinit)

    def deinit(self):
        if self._zmq:
            self._zmq.destroy(linger=5)

    def start(self):
        # Create a temporary fifo for IPC with ODR-DabMux over ZMQ
        self._zmqsock_path = utils.create_fifo()

        # Load ODR-DabMux configuration into memory
        self.config = ODRMuxConfig(self._zmqsock_path, self._streams)
        cfgfile = self._srvcfg['dab']['mux_config']
        if not self.config.load(cfgfile):
            logger.error(f'Unable to load DAB multiplexer configuration: {cfgfile}')
            return False

        # Start the DABServer thread
        try:
            self._odr = ODRServer(self._srvcfg)
            self._odr.start()
        except:
            err = 'Unable to start DAB server thread.'
            try:
                raise
            except KeyError as e:
                logger.error(f'{err} check configuration. {e}')
                return False
            except OSError as e:
                logger.error(f'{err} check output path. {e}')
                return False
            except Exception as e:
                logger.error(f'{err} {e}')
                return False

        # TODO check if multiplexer and modulator were successfully started

        # Connect to the multiplexer ZMQ socket
        self.zmqsock = self._zmq.socket(zmq.REQ)
        self.zmqsock.connect(f'ipc://{self._zmqsock_path}')

        # Start a watcher thread to process messages from the CAPServer
        try:
            self._watcher = DABWatcher(self._srvcfg, self._q, self.zmqsock, self._streams, self.config)
            self._watcher.start()
        except:
            err = 'Unable to start DAB watcher thread.'
            try:
                raise
            except KeyError as e:
                logger.error(f'{err} Check configuration. {e}')
                return False
            except OSError as e:
                logger.error(f'{err} invalid streams config. {e}')
                return False
            except Exception as e:
                logger.error(f'{err} {e}')
                return False

        return True

    def stop(self):
        if self.config is None:
            return

        # Remove the ZMQ ODR-DabMux IPC FIFO
        if self.zmqsock is not None:
            self.zmqsock.disconnect(f'ipc://{self._zmqsock_path}')
            utils.remove_fifo(self._zmqsock_path)

        if self._odr is not None:
            self._odr.join()
        if self._watcher is not None:
            self._watcher.join()

    def restart(self):
        if self.config is None:
            return False

        # Shutdown all DAB threads
        self.stop()

        # Start the server back up
        return self.start()

    # Return the status of the (DAB Server, DAB watcher, DAB Multiplexer, DAB MOdulator)
    def status(self):
        if self.config is None:
            return (False, False, False, False)

        server = self._odr.is_alive() if self._odr is not None else None
        watcher = self._watcher.is_alive() if self._watcher is not None else None
        # FIXME check these properly
        mux = subproc.run(('pgrep', 'odr-dabmux'), capture_output=True).returncode == 0
        mod = subproc.run(('pgrep', 'odr-dabmod'), capture_output=True).returncode == 0

        return (server, watcher, mux, mod)
