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

import configparser                         # Python INI file parser
import logging                              # Logging facilities
import multiprocessing                      # Multiprocessing support (for running data streams in the background)
import time                                 # For sleep support
from dab.audio import DABAudioStream        # DAB audio (DAB/DAB+) stream
from dab.data import DABDataStream          # DAB data (packet mode) stream
from dab.streamscfg import StreamsConfig    # streams.ini config
import utils

logger = logging.getLogger('server.dab')

class DABStreams():
    """ Class that manages individual DAB stream threads """

    def __init__(self, srvcfg: configparser.ConfigParser):
        # Set spawn instead of fork, locks up dialog otherwise (TODO find out why)
        multiprocessing.set_start_method('spawn')

        self._srvcfg = srvcfg

        self.config = StreamsConfig()
        self.streams = []

    def _start_stream(self, stream, index, output, streamcfg):
        try:
            if streamcfg['output_type'] == 'data':
                thread = DABDataStream(self._srvcfg, stream, streamcfg, output)
            else:
                thread = DABAudioStream(self._srvcfg, stream, streamcfg, output)

            thread.start()

            self.streams.insert(index, (stream, thread, streamcfg, output))
        except:
            try:
                self.streams.insert(index, (stream, None, streamcfg, None))

                raise
            except KeyError as e:
                raise Exception(f'Check configuration. {e}')
            except OSError as e:
                raise Exception(f'Invalid streams config. {e}')
            except Exception as e:
                raise Exception(e)

    def start(self):
        # Load streams.ini configuration into memory
        cfgfile = self._srvcfg['dab']['stream_config']
        if not self.config.load(cfgfile):
            logger.error(f'Unable to load DAB streams configuration: {cfgfile}')
            return False

        # Start all streams one by one
        i = 0
        ret = True
        for stream in self.config.cfg.sections():
            logger.info(f'Starting up DAB stream {stream}...')

            # Create a temporary FIFO for output
            output = utils.create_fifo()

            try:
                self._start_stream(stream, i, output, self.config.cfg[stream])
            except Exception as e:
                logger.error(f'Unable to start DAB stream "{stream}". {e}.')

                if output is not None:
                    utils.remove_fifo(output)

                ret = False
            else:
                i += 1

        return ret

    def getcfg(self, stream, default=False):
        """ Get the specified stream's configuration """

        if default:
            try:
                return self.config.cfg[stream]
            except KeyError:
                return None
        else:
            for s, _, c, _ in self.streams:
                if s == stream:
                    return c

            return None

    def setcfg(self, stream, newcfg=None):
        """ Change the configuration for a stream, used for stream replacement mainly """

        i = 0
        for s, t, c, o in self.streams:
            # Get the current stream
            if s == stream and c is not None:
                # Don't continue if we're already running with the provided config
                if newcfg == c:
                    return

                # Restore to the original stream
                if newcfg is None:
                    newcfg = self.config.cfg[stream]

                # Stop the old stream
                if t is not None:
                    t.join()

                    # Attempt terminating if joining wasn't successful (in case of a process)
                    if t.is_alive() and isinstance(t, multiprocessing.Process):
                        t.terminate()

                        # A last resort
                        if t.is_alive():
                            t.kill()

                    # Allow sockets some time to unbind (FIXME needed?)
                    time.sleep(4)
                self.streams.pop(i)

                # And fire up the new one
                self._start_stream(stream, i, o, newcfg)
                return

            i += 1

    def stop(self):
        if self.config is None:
            return

        for _, t, _, o in self.streams:
            if t is not None:
                t.join()

                # Attempt terminating if joining wasn't successful (in case of a process)
                if t.is_alive() and isinstance(t, multiprocessing.Process):
                    t.terminate()

                    # A last resort
                    if t.is_alive():
                        t.kill()

            if o is not None:
                utils.remove_fifo(o)

        self.streams = []

    def restart(self):
        if self.config is None:
            return False

        # Allow sockets some time to unbind
        time.sleep(4)

        self.stop()
        return self.start()

    def status(self):
        streams = []

        if self.config is not None:
            for s, t, _, _ in self.streams:
                streams.append((s, t.is_alive() if t is not None else None))

        return streams
