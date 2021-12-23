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

import copy                                                         # For saving/restoring Config objects
import os                                                           # For file I/O
import logging                                                      # Logging facilities
from dab.boost_info_parser import BoostInfoTree, BoostInfoParser    # C++ Boost INFO format parser (used for dabmux.cfg)

logger = logging.getLogger('server.dab')

# ODR-DabMux config file wrapper class
class ODRMuxConfig():
    def __init__(self, telnetport):
        self.p = BoostInfoParser()
        self.telnetport = telnetport

        self.oldcfg = None

    def load(self, cfgfile):
        if cfgfile == None:
            return False

        self.file = cfgfile

        # attempt to read the file
        if cfgfile != None and os.path.isfile(cfgfile):
            self.p.read(cfgfile)
            self.cfg = self.p.getRoot()

            # overwrite the default telnetport with the port specified in the server settings file
            self.cfg.remotecontrol['telnetport'] = str(self.telnetport)
            self.write()

            return True

        logger.warning(f'Unable to read {cfgfile}, creating a new config file')

        # generate a new config file otherwise
        self.cfg = BoostInfoTree()

        # load in defaults, refer to:
        # - https://github.com/Opendigitalradio/ODR-DabMux/blob/master/doc/example.mux
        # - https://github.com/Opendigitalradio/ODR-DabMux/blob/master/doc/advanced.mux

        self.cfg.general['dabmode'] = '1'               # DAB Transmission mode (https://en.wikipedia.org/wiki/Digital_Audio_Broadcasting#Bands_and_modes)
        self.cfg.general['nbframes'] = '0'              # Don't limit the number of ETI frames generated
        self.cfg.general['syslog'] = 'false'
        self.cfg.general['tist'] = 'false'              # Disable downloading leap second information
        self.cfg.general['managementport'] = '0'        # Disable management port

        self.cfg.remotecontrol['telnetport'] = str(self.telnetport)

        self.cfg.ensemble['id'] = '0x8FFF'               # Default to The Netherlands
        self.cfg.ensemble['ecc'] = '0xE3'
        self.cfg.ensemble['local-time-offset'] = 'auto'
        self.cfg.ensemble['international-table'] = '1'
        self.cfg.ensemble['reconfig-counter'] = 'hash'   # Enable FIG 0/7
        self.cfg.ensemble['label'] = 'DAB Ensemble'      # Set a generic default name
        self.cfg.ensemble['shortlabel'] = 'DAB'

        #root.services
        # Create a default Pseudo alarm announcement subchannel
        #  This sub-channel is an integral part of the PoC and aims to support warning messages on devices that don't
        #  support DAB-EWF or even the DAB Alarm Announcement.
        self.cfg.ensemble.announcements.alarm['cluster']
        self.cfg.ensemble.announcements.alarm.flags['Alarm'] = 'true'
        self.cfg.ensemble.announcements.alarm['subchannel'] = 'sub-alarm'

        self.cfg.services['srv-alarm']['id'] = '0x8AAA'
        self.cfg.services['srv-alarm']['label'] = 'Alarm announcement'
        self.cfg.services['srv-alarm']['shortlabel'] = 'Alarm'
        self.cfg.services['srv-alarm']['pty'] = '3'
        self.cfg.services['srv-alarm']['pty-sd'] = 'static'
        self.cfg.services['srv-alarm']['announcements']['Alarm'] = 'true'
        self.cfg.services['srv-alarm']['announcements']['clusters'] = '1'

        # FIXME generate subchannel on the fly based on streams.ini
        self.cfg.subchannels['sub-alarm']['type'] = 'dabplus'
        self.cfg.subchannels['sub-alarm']['bitrate'] = '96'
        self.cfg.subchannels['sub-alarm']['id'] = '1'
        self.cfg.subchannels['sub-alarm']['protection-profile'] = 'EEP_A'
        self.cfg.subchannels['sub-alarm']['protection'] = '3'
        self.cfg.subchannels['sub-alarm']['inputproto'] = 'zmq'
        self.cfg.subchannels['sub-alarm']['inputuri'] = 'tcp://*:39801'
        self.cfg.subchannels['sub-alarm']['zmq-buffer'] = '40'
        self.cfg.subchannels['sub-alarm']['zmq-prebuffering'] = '20'

        self.cfg.components['comp-alarm']['type'] = '2'                                 # Type 2 = multi-channel
        self.cfg.components['comp-alarm']['service'] = 'srv-alarm'
        self.cfg.components['comp-alarm']['subchannel'] = 'sub-alarm'
        self.cfg.components['comp-alarm']['user-applications']['userapp'] = 'slideshow' # Enable MOT slideshow

        # Output to stdout because we'll be piping the output into ODR-DabMux
        self.cfg.outputs['stdout'] = 'fifo:///dev/stdout?type=raw'

        self.write()

        return True

    def save(self):
        self.oldcfg = copy.deepcopy(self.cfg)

    def restore(self):
        if self.oldcfg == None:
            return

        self.cfg = self.oldcfg
        self.oldcfg = None

    def write(self):
        self.p.load(self.cfg)
        self.p.write(self.file)
