import configparser             # Python INI file parser
import logging                  # Logging facilities
import os                       # For checking if files exist
import subprocess as subproc    # Support for starting subprocesses
import threading                # Threading support (for running streams in the background)
import time                     # For sleep support

logger = logging.getLogger('server.dab')

# This class represents every stream as a thread, defined in streams.ini
class DABStream(threading.Thread):
    def __init__(self, config, name, index, streamcfg):
        threading.Thread.__init__(self)

        self.name = name
        self.streamcfg = streamcfg
        self.portrange = (39801, 39898)           # XXX XXX XXX FIXME don't hardcode ports, get from config file

        # Get which output port which should use
        self.port = self.portrange[0] + index

        self.streamdir = f'{config["general"]["logdir"]}/streams/{self.name}'
        self.binpath = config['dab']['odrbin_path']

        self.audio = None
        self.pad = None

        # Create a directory structure for the stream to save logs to and load DLS and MOT information from
        os.makedirs(self.streamdir, exist_ok=True)
        os.makedirs(f'{self.streamdir}/logs', exist_ok=True)
        if self.streamcfg.getboolean('dls_enable'):
            open(f'{self.streamdir}/dls.txt', 'a').close()
        if self.streamcfg.getboolean('mot_enable'):
            os.makedirs(f'{self.streamdir}/mot', exist_ok=True)

    def run(self):
        # Check if we have enough ports available in the specified portrange
        if self.port > self.portrange[1]:
            raise Exception('Too many streams running, no more available ports. Check configuration.')

        # If DLS and MOT are disabled, we won't need to start odr-padenc
        pad_enable = self.streamcfg.getboolean('dls_enable') and self.streamcfg.getboolean('mot_enable')

        # Save our logs (FIXME rotate logs)
        audiolog = open(f'{self.streamdir}/logs/audioenc.log', 'ab')
        if pad_enable:
            padlog = open(f'{self.streamdir}/logs/padenc.log', 'ab')

        # Start up odr-audioenc DAB/DAB+ audio encoder
        audioenc_cmdline = [
                            f'{self.binpath}/odr-audioenc',
                            f'--bitrate={self.streamcfg["bitrate"]}',
                            f'--output=tcp://localhost:{self.port}',
                            f'--pad-socket={self.name}',
                            f'--pad={self.streamcfg["pad_length"]}'
                           ]

        # Set the DAB type
        if self.streamcfg['output_type'] == 'dab':
            audioenc_cmdline.append('--dab')

        # Add the input to cmdline
        if self.streamcfg['input_type'] == 'gst':
            audioenc_cmdline.append(f'--gst-uri={self.streamcfg["input"]}')
        elif self.streamcfg['input_type'] == 'fifo':
            audioenc_cmdline.append(f'--input={self.streamdir}/{self.streamcfg["input"]}')
            audioenc_cmdline.append('--format=raw')
            audioenc_cmdline.append('--fifo-silence')
        elif self.streamcfg['input_type'] == 'file':
            audioenc_cmdline.append(f'--input={self.streamdir}/{self.streamcfg["input"]}')
            audioenc_cmdline.append('--format=wav')

        self.audio = subproc.Popen(audioenc_cmdline, stdout=audiolog, stderr=audiolog)

        # Start up odr-padenc PAD encoder
        if pad_enable:
            padenc_cmdline = [
                              f'{self.binpath}/odr-padenc',
                              f'--output={self.name}'
                             ]

            # Add DLS and MOT if enabled
            if self.streamcfg.getboolean('dls_enable'):
                padenc_cmdline.append(f'--dls={self.streamdir}/dls.txt')
            if self.streamcfg.getboolean('mot_enable'):
                padenc_cmdline.append(f'--dir={self.streamdir}/mot')
                padenc_cmdline.append(f'--sleep={self.streamcfg["mot_timeout"]}')

            self.pad = subproc.Popen(padenc_cmdline, stdout=padlog, stderr=padlog)

        # TODO quit odr-audioenc if odr-padenc exists

        # Send odr-dabmux's data to odr-dabmod. This operation blocks until the process in killed
        self.audio.communicate()[0]
        if pad_enable:
            self.pad.communicate()[0]

        audiolog.close()
        if pad_enable:
            padlog.close()

    # TODO log termination
    def join(self):
        if not self.is_alive():
            return

        if self.audio != None:
            self.audio.terminate()
        #if self.audio.poll() is None:
        #    pass
        #else:
        #    pass

        if self.pad != None:
            self.pad.terminate()
        #if self.pad.poll() is None:
        #    pass
        #else:
        #    pass

        # TODO consider deleting the stream directory structure on exiting the thread (or at least add an option in settings)

        super().join()

# Class that manages individual DAB stream threads
class DABStreams():
    def __init__(self, config):
        self._srvcfg = config

        self._streamscfg = None
        self._streams = []

    def _start_stream(self, stream, index, cfg):
        logger.info(f'Starting up DAB stream {stream}...')

        try:
            thread = DABStream(self._srvcfg, stream, index, cfg)
            thread.start()
            self._streams.insert(index, (stream, thread))
        except KeyError as e:
            logger.error(f'Unable to start DAB stream "{stream}", check configuration. {e}')
            return False
        except OSError as e:
            logger.error(f'Unable to start DAB stream "{stream}", invalid streams config. {e}')
            return False
        except Exception as e:
            logger.error(f'Unable to start DAB stream "{stream}". {e}')
            return False

        return True

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

    def chreplace(self, stream, newcfg):
        i = 0
        for s, t in self._streams:
            if s == stream:
                # Stop the old stream
                t.join()
                del self._streams[i]

                # Allow sockets some time to unbind (FIXME needed?)
                time.sleep(4)

                # And fire up the new one
                return self._start_stream(stream, i, newcfg)

            i += 1


    def stop(self):
        if self._streamscfg == None:
            return

        for stream in self._streams:
            if stream != None and stream[1] != None:
                stream[1].join()

        self._streams = []

    def restart(self):
        if self._streamscfg == None:
            return False

        # Allow sockets some time to unbind
        time.sleep(4)

        self.stop()
        return self.start()

    def status(self):
        if self._streamscfg == None:
            return []

        streams = []

        for stream in self._streams:
            streams.append((stream[0], stream[1].is_alive()))

        return streams
