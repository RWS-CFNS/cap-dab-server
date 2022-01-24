#
# Rewritten in Python from: https://github.com/Opendigitalradio/data-over-dab-example/blob/master/src/packager.cpp
#
# Copyright (C) 2017 Opendigitalradio (http://www.opendigitalradio.org/)
# Copyright (C) 2017 Felix Morgner <felix.morgner@hsr.ch>
# Copyright (C) 2017 Tobias Stauber <tobias.stauber@hsr.ch>
# Copyright (C) 2022 Bastiaan Teeuwen <bastiaan@mkcl.nl>
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
#    may be used to endorse or promote products derived from this software without
#    specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

from configparser import ConfigParser   # For parsing the server config
import os                               # For creating directories
import struct			                # For generating DAB MSC and Packet headers
import multiprocessing                  # Multiprocessing support (for running data streams in the background)
import utils

def _crc16(data:bytearray) -> bytes:
    """ Calculate Packet/MSC data group CRC according to ETSI EN 300 401 V2.1.1 Sections 5.3.2.3 and 5.3.3.4 """

    if data is None:
        return bytes(0)

    crc = 0xFFFF

    for e in data:
        x = (crc >> 8) ^ e
        x = (x ^ (x >> 4))
        crc = ((crc << 8) & 0xFFFF) ^ ((x << 12) & 0xFFFF) ^ ((x << 5) & 0xFFFF) ^ (x & 0xFFFF)

    crc = ~crc & 0xFFFF

    return struct.pack('!H', crc)

def _to_bytes(x:int) -> bytes:
    """ Convert an single byte represented as an int to a big endian byte object """

    return x.to_bytes(1, 'big')

class MSCDataGroupBuilder():
    """ Class to split arbitrary data into MSC Data Groups """

    def __init__(self):
        self.last_data = None
        self.coni = 15
        self.repi = 0

    def _build_header(self) -> bytes:
        """ Build the MSC data group header (ETSI EN 300 401 V2.1.1 Section 5.3.3) """

        byte0  = 0 << 7         # Extension flag
        byte0 |= 1 << 6         # CRC flag
        byte0 |= 0 << 5         # Segment flag
        byte0 |= 0 << 4         # User access flag
        byte1  = 0              # Data group type
        byte1 |= self.coni << 4 # Continuity index
        byte1 |= self.repi      # Repetition index

        return struct.pack('<cc', _to_bytes(byte0), _to_bytes(byte1))

    def build(self, data:bytes) -> bytearray:
        if self.last_data == None or self.last_data != data:
            self.coni = (self.coni + 1) % 16
            self.repi = 0
        elif self.repi > 0:
            self.repi -= 1
        else:
            self.repi = 0

        self.last_data = data

        packet = bytearray(self._build_header())
        packet.extend(data)
        packet.extend(_crc16(packet))

        return packet

class PacketBuilder():
    PACKET_LENGTH =      (24,                    48,                    72,                    96                  )
    PACKET_DATA_LENGTH = (PACKET_LENGTH[0] - 5,  PACKET_LENGTH[1] - 5,  PACKET_LENGTH[2] - 5,  PACKET_LENGTH[3] - 5)

    def __init__(self, packet_address:int):
        self.first_last = 0b11
        self.coni = 0
        self.address = packet_address & 0xFFFF

    def _build_header(self, packet_length:int, data_length:int) -> bytes:
        """ Build the Packet header (ETSI EN 300 401 V2.1.1 Section 5.3.2.1) """

        byte0 = 0

        # Packet length
        if packet_length == self.PACKET_LENGTH[3]:
            byte0 = 0b11 << 6
        elif packet_length == self.PACKET_LENGTH[2]:
            byte0 = 0b10 << 6
        elif packet_length == self.PACKET_LENGTH[1]:
            byte0 = 0b01 << 6
        elif packet_length == self.PACKET_LENGTH[0]:
            byte0 = 0b00 << 6

        byte0 |= self.coni << 4                 # Continuity Index
        self.coni = (self.coni + 1) % 4
        byte0 |= self.first_last << 2           # First/Last
        byte0 |= 0b11 & (self.address >> 8)     # Packet address
        byte1  = self.address & 0xFF
        byte2  = 0 << 7                         # Command = Data packet
        byte2 |= data_length                    # Useful data length

        return struct.pack('<ccc', _to_bytes(byte0), _to_bytes(byte1), _to_bytes(byte2))

    def _build_packet(self, data:bytes, packet_length:int, data_length:int) -> bytearray:
        # Calculate number of padding bytes conforming to ETSI EN 300 401 V2.1.1 Section 5.3.2.2
        padding_length = packet_length - 5 - data_length

        packet = bytearray(self._build_header(packet_length, data_length))
        packet.extend(data)
        packet += _to_bytes(0b0) * padding_length
        packet.extend(_crc16(packet))

        return packet

    def build(self, data:bytes) -> bytearray:
        data_length = len(data)
        i = 0

        for i in reversed(range(-1, len(self.PACKET_LENGTH))):
            # Attempt to fit data into the smallest possible packet size
            if i < 0 or data_length > self.PACKET_DATA_LENGTH[i]:
                if i == 3:
                    # Data is too large, split into multiple packets
                    if self.first_last == 0b01 or self.first_last == 0b11:
                        self.first_last = 0b10
                    elif self.first_last == 0b10:
                        self.first_last = 0b00

                    # Split into multiple packets, handle this recursively
                    first_part = data[:self.PACKET_DATA_LENGTH[i]]
                    first_packet = self._build_packet(first_part, self.PACKET_LENGTH[i], self.PACKET_DATA_LENGTH[i])
                    other_packets = self.build(data[self.PACKET_DATA_LENGTH[i]:])
                    first_packet.extend(other_packets)

                    return first_packet
                else:
                    if self.first_last == 0b00 or self.first_last == 0b10:
                        self.first_last = 0b01
                    else:
                        self.first_last = 0b11

                    return self._build_packet(data, self.PACKET_LENGTH[i + 1], data_length)

        # FIXME duplicate code
        if self.first_last == 0b00 or self.first_last == 0b10:
            self.first_last = 0b01
        else:
            self.first_last = 0b11

        return self._build_packet(data, self.PACKET_LENGTH[i + 1], data_length)

class DABDataStream(multiprocessing.Process):
    """
    This class represents a data stream as a thread, defined in streams.ini
    """

    # FIFO read buffer size
    # TODO configure in GUI
    BUFFER_SIZE = 1024

    def __init__(self, srvcfg:ConfigParser, name:str, streamcfg, output_path:str):
        multiprocessing.Process.__init__(self)

        self.name = name
        self.input_path = streamcfg['input']
        self.output_path = output_path

        self.group_builder = MSCDataGroupBuilder()
        self.packet_builder = PacketBuilder(1000) # FIXME don't hardcode the packet address, allow configuring in GUI

        self.streamdir = f'{srvcfg["general"]["logdir"]}/streams/{self.name}'

        # Create a directory structure for the stream to save logs to and load DLS and MOT information from
        os.makedirs(self.streamdir, exist_ok=True)
        os.makedirs(f'{self.streamdir}/logs', exist_ok=True)

        # TODO check if this is a fifo and create if needed/check for existence file
        path = streamcfg['input']
        if streamcfg['input_type'] == 'fifo':
            utils.create_fifo(path)
        elif streamcfg['input_type'] == 'file':
            if not os.path.exists(path):
                raise Exception('DAB data source file does not exist!')

            if not os.path.isfile(path):
                raise Exception('DAB data source is not a file!')

        self._running = True

    def run(self):
        """ Start this data stream """

        while self._running:
            with open(self.input_path, 'rb') as infile:
                with open(self.output_path, 'wb') as outfifo:
                    # Read in blocks to prevent having to load all file contents into memory
                    while self._running:
                        indata = infile.read(self.BUFFER_SIZE)

                        if len(indata) == 0:
                            # EOF
                            break

                        # Pack the data into MSC Data Groups
                        group = self.group_builder.build(indata)
                        # Split the MSC Data Groups into DAB Packets
                        packets = self.packet_builder.build(group)

                        # Write our packets to odr-dabmux
                        outfifo.write(packets)
                        outfifo.flush()

    def join(self, timeout:int=3):
        """ Stop this data stream """

        if not self.is_alive():
            return

        self._running = False

        # TODO consider deleting the stream directory structure on exiting the thread (or at least add an option in settings)

        super().join(timeout)
