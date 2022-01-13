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

import configparser                     # Python INI file parser
import logging                          # Logging facilities
import os                               # For creating directories
import time                             # For sleep support
import utils
from dab.audio import DABAudioStream
from dab.data import DABDataStream

logger = logging.getLogger('server.dab')

# Class that manages individual DAB stream threads
class DABStreams():
    def __init__(self, config):
        self._srvcfg = config

        self._streamscfg = None
        self.streams = []

    def _start_stream(self, stream, index, streamcfg):
        # Create a temporary FIFO for output
        out = utils.create_fifo()

        try:
            if streamcfg['output_type'] == 'data':
                logger.info(f'Starting up DAB data stream {stream}...')
                thread = DABDataStream(self._srvcfg, stream, index, streamcfg, out)
            else:
                logger.info(f'Starting up DAB audio stream {stream}...')

                thread = DABAudioStream(self._srvcfg, stream, index, streamcfg, out)

            thread.start()

            self.streams.insert(index, (stream, thread, streamcfg, out))

            return True
        except KeyError as e:
            logger.error(f'Unable to start DAB stream "{stream}", check configuration. {e}')
        except OSError as e:
            logger.error(f'Unable to start DAB stream "{stream}", invalid streams config. {e}')
        except Exception as e:
            logger.error(f'Unable to start DAB stream "{stream}". {e}')

        if out is not None:
            utils.remove_fifo(out)

        return False

    def start(self):
        # Load streams configuration into memory
        cfgfile = self._srvcfg['dab']['stream_config']
        os.makedirs(os.path.dirname(cfgfile), exist_ok=True)
        self._streamscfg = configparser.ConfigParser()
        if os.path.isfile(cfgfile):
            self._streamscfg.read(cfgfile)
        else:
            logger.error(f'Unable to load DAB stream configuration: {cfgfile}')
            return False

        # Start all streams one by one
        i = 0
        ret = True
        for stream in self._streamscfg.sections():
            if self._start_stream(stream, i, self._streamscfg[stream]):
                i += 1
            else:
                ret = False

        return ret

    # Get the specified stream's configuration
    def getcfg(self, stream, default=False):
        if default:
            try:
                return self._streamscfg[stream]
            except KeyError:
                return None
        else:
            for s, t, c, o in self.streams:
                if s == stream:
                    return c

            return None

    # Change the configuration for a stream, used for stream replacement mainly
    def setcfg(self, stream, newcfg=None):
        i = 0
        for s, t, c, o in self.streams:
            # Get the current stream
            if s == stream:
                # Check if this stream is an audio stream
                if c['output_type'] == 'data':
                    return

                # Restore to the original stream
                if newcfg is None:
                    newcfg = self._streamscfg[stream]

                # Stop the old stream
                t.join()
                del self.streams[i]

                # Allow sockets some time to unbind (FIXME needed?)
                time.sleep(4)

                # And fire up the new one
                return self._start_stream(stream, i, newcfg)

            i += 1


    def stop(self):
        if self._streamscfg is None:
            return

        for s, t, c, o in self.streams:
            if o is not None:
                utils.remove_fifo(o)
            t.join()

        self.streams = []

    def restart(self):
        if self._streamscfg is None:
            return False

        # Allow sockets some time to unbind
        time.sleep(4)

        self.stop()
        return self.start()

    def status(self):
        if self._streamscfg is None:
            return []

        streams = []

        for s, t, c, o in self.streams:
            streams.append((s, t.is_alive()))

        return streams
