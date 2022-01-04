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

import os       # For file I/O
import stat     # For checking if output is a FIFO
import tempfile # For creating a temporary FIFO
import uuid     # For generating random FIFO file names
import zmq      # For signalling (alarm) announcements to ODR-DabMux

# Log via logging.error or logging.warning depending on whether strict CAP parsing is enforced or not
# Return bool:
# - True if strict parsing is enabled
# - False if strict parsing is disabled
def logger_strict(logger, msg):
    if strict:
        logger.error(msg)
        return True
    else:
        logger.warning(msg)
        return False

# Create a new fifo (based on an specified path or if path is None, a new temporary file)
def create_fifo(path=None):
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

def remove_fifo(path):
    try:
        os.remove(path)
        os.rmdir(os.path.dirname(path))
    except OSError:
        pass

# Send a message over ZeroMQ to ODR-DabMux
def mux_send(sock, msgs):
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
