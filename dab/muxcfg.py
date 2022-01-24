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

import copy                                                         # For saving/restoring Config objects
import os                                                           # For file I/O
import logging                                                      # Logging facilities
from dab.boost_info_parser import BoostInfoTree, BoostInfoParser    # C++ Boost INFO format parser (used for dabmux.cfg)
from dab.streams import DABStreams                               	# DAB streams manager

logger = logging.getLogger('server.dab')

class ODRMuxConfig():
    """ ODR-DabMux config file wrapper class """

    def __init__(self, zmqfifo: str, streams: DABStreams):
        self._parser = BoostInfoParser()

        self._zmqfifo = zmqfifo
        self._streams = streams

        self._cfgfile = None
        self._oldcfg = None
        self.cfg = None

    def _overwrite(self, cfg:BoostInfoTree):
        """ Generate subchannels and components from streams.ini """

        # overwrite/set zmqendpoint to the temp file generated by DABServer
        cfg.remotecontrol['zmqendpoint'] = f'ipc://{self._zmqfifo}'

        cfg['subchannels']
        del cfg['subchannels']
        cfg['components']

        # Generate subchannels from streams.ini
        i = 0
        for s, _, c, o in self._streams.streams:
            cfg.subchannels[s]['id'] = str(i)

            output_type = c['output_type']
            if output_type == 'dabplus':
                cfg.subchannels[s]['type'] = 'dabplus'
            elif output_type == 'dab':
                cfg.subchannels[s]['type'] = 'audio'
            elif output_type == 'data':
                cfg.subchannels[s]['type'] = 'packet'
            else:
                logger.error(f'Invalid output_type: {output_type}')

            cfg.subchannels[s]['bitrate'] = c['bitrate']
            cfg.subchannels[s]['protection-profile'] = c['protection_profile']
            cfg.subchannels[s]['protection'] = c['protection']

            # Set our temporary output FIFO for IPC between odr-audioenc and odr-dabmux
            input_type = c['input_type']
            if input_type == 'gst':
                cfg.subchannels[s]['inputproto'] = 'zmq'
                cfg.subchannels[s]['inputuri'] = f'ipc://{o}'
                cfg.subchannels[s]['zmq-buffer'] = '40'
                cfg.subchannels[s]['zmq-prebuffering'] = '20'
            elif input_type in ('file', 'fifo'):
                cfg.subchannels[s]['inputproto'] = 'file'
                if output_type == 'data':
                    cfg.subchannels[s]['inputuri'] = o
                else:
                    cfg.subchannels[s]['inputuri'] = c['input']

                if input_type == 'fifo':
                    cfg.subchannels[s]['nonblock'] = 'true'

            i += 1

        # Generate components
        for _, component in cfg.components:
            stream_cfg = self._streams.getcfg(str(component['subchannel']))

            if stream_cfg is None:
                continue

            output_type = stream_cfg['output_type']
            if output_type == 'dabplus':
                component['type'] = '2'     # multi-channel audio stream
            elif output_type == 'dab':
                component['type'] = '2'     # multi-channel audio stream
            elif output_type == 'data':
                component['type'] = '59'    # IP data stream
            else:
                logger.error(f'Invalid output_type: {output_type}')

            #cfg.components[comp_name]['service'] = 'srv-audio' # FIXME FIXME FIXME configure this in the GUI!!!
            #cfg.components[comp_name]['subchannel'] = s
            if stream_cfg.getboolean('mot_enable'):
                component['user-applications']['userapp'] = 'slideshow'

        return True

    def load(self, cfgfile:str) -> bool:
        """ Load a new config file into memory """

        if cfgfile is None:
            return False

        self._cfgfile = cfgfile

        # attempt to read the file
        if os.path.isfile(cfgfile):
            self._parser.read(cfgfile)
            self.cfg = self._parser.getRoot()

            if not self._overwrite(self.cfg):
                return False

            self.write()

            return True

        # generate a new config file otherwise
        logger.warning(f'Unable to read {cfgfile}, creating a new multiplexer config file')
        self.cfg = BoostInfoTree()

        # load in defaults, refer to:
        # - https://github.com/Opendigitalradio/ODR-DabMux/blob/master/doc/example.mux
        # - https://github.com/Opendigitalradio/ODR-DabMux/blob/master/doc/advanced.mux

        # General server configuration, these parameters never have to be modified
        self.cfg.general['dabmode'] = '1'               # DAB Transmission mode (https://en.wikipedia.org/wiki/Digital_Audio_Broadcasting#Bands_and_modes)
        self.cfg.general['nbframes'] = '0'              # Don't limit the number of ETI frames generated
        self.cfg.general['syslog'] = 'false'
        self.cfg.general['tist'] = 'false'              # Disable downloading leap second information
        self.cfg.general['managementport'] = '0'        # Disable management port

        # Some sane ensemble defaults
        self.cfg.ensemble['id'] = '0x8FFF'               # Default to The Netherlands
        self.cfg.ensemble['ecc'] = '0xE3'
        self.cfg.ensemble['local-time-offset'] = 'auto'
        self.cfg.ensemble['international-table'] = '1'
        self.cfg.ensemble['reconfig-counter'] = 'hash'   # Enable FIG 0/7
        self.cfg.ensemble['label'] = 'DAB Ensemble'      # Set a generic default name
        self.cfg.ensemble['shortlabel'] = 'DAB'

        if not self._overwrite(self.cfg):
            return False

        # Output to stdout because we'll be piping the output into ODR-DabMux
        self.cfg.outputs['stdout'] = 'fifo:///dev/stdout?type=raw'

        self.write()

        return True

    def save(self):
        """ Save a temporary copy of the current config file in memory """

        self._oldcfg = copy.deepcopy(self.cfg)

    def restore(self):
        """ Restore the temporary copy made with save() """

        if self._oldcfg is None:
            return

        self.cfg = self._oldcfg
        self._oldcfg = None

    def write(self):
        """ Write the config to a file """

        self._parser.load(self.cfg)
        self._parser.write(self._cfgfile)
