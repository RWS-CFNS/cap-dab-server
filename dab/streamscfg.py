#
#    CFNS - Rijkswaterstaat CIV, Delft © 2022 <cfns@rws.nl>
#
#    Copyright 2022 Bastiaan Teeuwen <bastiaan@mkcl.nl>
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

import configparser # Python INI file parser
import copy         # For saving/restoring Config objects
import os           # For file I/O
import logging      # Logging facilities

logger = logging.getLogger('server.dab')

# streams.ini config file wrapper class
class StreamsConfig():
    def __init__(self):
        self._cfgfile = None
        self._oldcfg = None
        self.cfg = configparser.ConfigParser()

    def load(self, cfgfile):
        if cfgfile is None:
            return False

        self._cfgfile = cfgfile

        # attempt to read the file
        if os.path.isfile(cfgfile):
            self.cfg.read(cfgfile)

            return True

        # create a new config file if it doesn't exist yet
        logger.warning(f'Unable to read {cfgfile}, creating a new streams.ini config file')
        os.makedirs(os.path.dirname(cfgfile), exist_ok=True)
        open(cfgfile, 'w').close()

        return True

    def save(self):
        self._oldcfg = copy.deepcopy(self.cfg)

    def restore(self):
        if self._oldcfg is None:
            return

        self.cfg = self._oldcfg
        self._oldcfg = None

    def write(self):
        with open(self._cfgfile, 'w') as f:
            self.cfg.write(f)
