#
#    CFNS - Rijkswaterstaat CIV, Delft © 2021 <cfns@rws.nl>
#
#    Copyright 2021 Bastiaan Teeuwen <bastiaan@mkcl.nl>
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

import os                           # For file I/O
import stat                         # For checking if output is a FIFO
import logging                      # Logging facilities
import subprocess as subproc        # Support for starting subprocesses
import threading                    # Threading support (for running odr-dabmux and odr-dabmod in the background)
import time                         # For sleep support
from dab.watcher import DABWatcher  # DAB CAP message watcher
from dab.muxcfg import ODRMuxConfig # odr-dabmux config

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

    def run(self):
        # TODO rotate this log, this is not so straightforward it appears
        muxlog = open(f'{self.logdir}/dabmux.log', 'ab')
        modlog = open(f'{self.logdir}/dabmod.log', 'ab')

        # check if there's already a file with the same name as our output
        if os.path.exists(self.output):
            # if this is a fifo, we don't need to take any action
            if not stat.S_ISFIFO(os.stat(self.output).st_mode):
                # otherwise delete the file/dir
                if os.path.isfile(self.output):
                    os.remove(self.output)
                elif os.path.isdir(self.output):
                    os.rmdir(self.output)
                else:
                    raise Exception(f'Unable to remove already existing output path: {self.output}')

                # Create the FIFO that odr-dabmod outputs to
                os.mkfifo(self.output)
        else:
            # Create the FIFO that odr-dabmod outputs to
            os.mkfifo(self.output)

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

        modlog.close()
        muxlog.close()

    def join(self):
        if not self.is_alive():
            return

        # Terminate the modulator and multiplexer
        if self.mod != None:
            self.mod.terminate()
            if self.mod.poll() is None:
                logger.info('DAB modulator terminated successfully!')
            else:
                logger.error('Terminating DAB modulator failed. Attempt quitting manually.')

        if self.mux != None:
            self.mux.terminate()
            if self.mux.poll() is None:
                logger.info('DAB modulator terminated successfully!')
            else:
                logger.error('Terminating DAB multiplexer failed. Attempt quitting manually.')

        # Remove the fifo file that was used as output
        os.remove(self.output)

        super().join()

class DABServer():
    def __init__(self, config, q, streams):
        self._srvcfg = config
        self._q = q
        self._streams = streams

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
        except OSError as e:
            logger.error(f'Unable to start DAB server thread, check output path. {e}')
            return False
        except Exception as e:
            logger.error(f'Unable to start DAB server thread. {e}')
            return False

        # TODO check if multiplexer and modulator were successfully started

        # Start a watcher thread to process messages from the CAPServer
        try:
            self._watcher = DABWatcher(self._srvcfg, self._q, self._streams)
            self._watcher.start()
        except KeyError as e:
            logger.error(f'Unable to start DAB watcher thread, check configuration. {e}')
            return False
        except OSError as e:
            logger.error(f'Unable to start DAB watcher thread, invalid streams config. {e}')
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

        server = self._odr.is_alive() if self._odr != None else False
        watcher = self._watcher.is_alive() if self._watcher != None else False
        # FIXME check these properly
        mux = subproc.run(('pgrep', 'odr-dabmux'), capture_output=True).returncode == 0
        mod = subproc.run(('pgrep', 'odr-dabmod'), capture_output=True).returncode == 0

        return (server, watcher, mux, mod)
