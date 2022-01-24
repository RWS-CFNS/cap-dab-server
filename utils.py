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

from configparser import ConfigParser           # For parsing the server config
import copy                                     # For creating a copy on the stream configuration
import logging                                  # Logging facilities
import os                                       # For file I/O
import stat                                     # For checking if output is a FIFO
import tempfile                                 # For creating a temporary FIFO
import uuid                                     # For generating random FIFO file names
import zmq                                      # For signalling (alarm) announcements to ODR-DabMux
from dab.boost_info_parser import BoostInfoTree # For parsing the multiplexer config
from dab.streams import DABStreams              # DAB streams

def logger_strict(logger:logging.Logger, strict:bool, msg:str) -> bool:
    """
    Log via logging.error or logging.warning depending on whether strict CAP parsing is enforced or not.

    Return True if strict parsing is enabled or False if strict parsing is disabled
    """

    if strict:
        logger.error(msg)
        return True
    else:
        logger.warning(msg)
        return False

def create_fifo(path:str=None) -> str:
    """
    Create a new named pipe (FIFO) with the specified path. If path is None, a new temporary file will be created.

    An Exception exception is raised if the FIFO cannot be created.

    Return a string with the file path of the newly created FIFO
    """

    if path is None:
        # Create a new temporary file if no path was specified
        path = os.path.join(tempfile.mkdtemp(), str(uuid.uuid4()))
        os.mkfifo(path)
    else:
        # Check if there's already a file with the same name as our output
        if os.path.exists(path):
            # If this is a FIFO, we don't need to take any action
            if not stat.S_ISFIFO(os.stat(path).st_mode):
                # Otherwise delete the file/dir
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    os.rmdir(path)
                else:
                    raise Exception(f'Unable to remove already existing FIFO path: {path}')

                # Create the FIFO
                os.mkfifo(path)
        else:
            # Create the FIFO that odr-dabmod outputs to
            os.mkfifo(path)

    return path

def remove_fifo(path:str):
    """
    Remove a fifo created with create_fifo().

    An OSError exception is raised if the FIFO could not be removed.
    """

    try:
        os.remove(path)
        os.rmdir(os.path.dirname(path))
    except OSError:
        pass

def mux_send(sock, msgs:tuple) -> str | None:
    """
    Send a message over ZeroMQ to ODR-DabMux and wait for a reply.

    Return the received message
    """

    # TODO handle failed scenario

    # Perform a quick ping test
    sock.send(b'ping')
    data = sock.recv_multipart()
    if data[0].decode() != 'ok':
        return None

    # Send our actual command
    for i, part in enumerate(msgs):
        if i == len(msgs) - 1:
            f = 0
        else:
            f = zmq.SNDMORE

        sock.send(part.encode(), flags=f)

    # Wait for the results
    data = sock.recv_multipart()
    res = ''

    for i, part in enumerate(data):
        res += part.decode()

    return res

def replace_streams(zmqsock, srvcfg:ConfigParser, muxcfg:BoostInfoTree, streams:DABStreams, input_type:str=None, inputuri:str=None, data_streams:bool=False):
    """
    Replace all streams which support Alarm announcements with the specified input and input_type.

    An exception is raised in case any stream wasn't able to be replaced.
    """
    # FIXME the way this function is integrated in the application is not very elegant
    #       it works, but it's ugly

    alarm_on = input_type is not None or inputuri is not None

    for sname, service in muxcfg.services:
        # Check if this service supports alarm announcements
        # TODO also support Warning announcement
        alarm = service.announcements.getboolean('Alarm')
        if not alarm:
            continue

        if alarm_on:
            # Replace the service Label and PTY to the one configured for Alarm announcements
            # FIXME create a setting for this, don't hardcode!!!
            label = srvcfg['warning']['label']
            shortlabel = srvcfg['warning']['shortlabel']
            pty = srvcfg['warning']['pty']
        else:
            # Restore the original service labels
            # FIXME generate shortlabel if there's no shortlabel
            label = str(service['label'])
            shortlabel = str(service['shortlabel'])
            pty = str(service['pty'])

        mux_send(zmqsock, ('set', sname, 'label', f'{label},{shortlabel}'))
        if pty != '':
            mux_send(zmqsock, ('set', sname, 'pty', pty))

        # Get the streams corresponding to this service
        for _, component in muxcfg.components:
            if str(component.service) != sname:
                continue

            component_type = int(str(component.type))
            if not data_streams:
                # Skip non-audio components
                if component_type not in (0, 1, 2):
                    continue
            else:
                # Only packet data comonents
                if component_type != 59:
                    continue

            # Check if this name exists in the config too
            subchannel = str(component.subchannel)
            found = False

            # TODO can this be done prettier?
            for s, _, c, _ in streams.streams:
                if s == subchannel:
                    found = True

                    # TODO change DLS
                    if alarm_on:
                        # Create a copy of the stream's config
                        cfg = copy.deepcopy(c)

                        cfg['input_type'] = input_type
                        cfg['input'] = inputuri

                        cfg['dls_enable'] = 'no'
                        cfg['mot_enable'] = 'no'

                        # Perform stream replacement on the corresponding subchannel/stream
                        streams.setcfg(s, cfg)
                    else:
                        # Restore the old stream
                        streams.setcfg(s)

            if not found:
                raise Exception(f'Misconfiguration: stream "{subchannel}" was not found in streams.ini!')
