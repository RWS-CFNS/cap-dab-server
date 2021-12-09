import configparser             # Python INI file parser
import logging                  # Logging facilities
import os                       # For checking if files exist
import subprocess as subproc    # Support for starting subprocesses
import threading                # Threading support (for running streams in the background)
import time                     # For sleep support

logger = logging.getLogger('server.dab')

class DABStream(threading.Thread):
    def __init__(self, config, name, index, streamcfg):
        threading.Thread.__init__(self)

        self.logdir = config['general']['logdir']
        self.binpath = config['dab']['odrbin_path']

        self.name = name
        self.streamcfg = streamcfg
        self.portrange = (39801, 39898)           # XXX XXX XXX FIXME don't hardcode ports, get from config file

        # Get which output port which should use
        self.port = self.portrange[0] + index

    def run(self):
        # TODO save log files
        audiolog = open(f'{self.logdir}/audio-{self.name}.log', 'ab')
        padlog = open(f'{self.logdir}/pad-{self.name}.log', 'ab')

        # TODO fixme, customized exception
        if self.port > self.portrange[1]:
            raise Exception

        # Start up odr-audioenc DAB/DAB+ audio encoder
        # TODO handle dab or dabplus type
        # TODO set protection
        audioenc_cmdline = (
                            f'{self.binpath}/odr-audioenc',
                            f'--input={self.streamcfg["input"]}',
                             '--format=raw',
                             '--fifo-silence',
                            f'--bitrate={self.streamcfg["bitrate"]}',
                            f'--output=tcp://localhost:{self.port}',
                            f'--pad-socket={self.name}',
                            f'--pad={self.streamcfg["pad_length"]}'
                           )
        self.audio = subproc.Popen(audioenc_cmdline, stdout=audiolog, stderr=audiolog)

        # Start up odr-padenc PAD encoder
        padenc_cmdline = (
                          f'{self.binpath}/odr-padenc',
                          f'--dls={self.streamcfg["dls_file"]}',
                          f'--dir={self.streamcfg["mot_dir"]}',
                          f'--output={self.name}',
                          f'--sleep={self.streamcfg["mot_timeout"]}'
                         )
        self.pad = subproc.Popen(padenc_cmdline, stdout=padlog, stderr=padlog)

        # Send odr-dabmux's data to odr-dabmod. This operation blocks until the process in killed
        #out = mod.communicate()[0]
        self.audio.communicate()[0]
        self.pad.communicate()[0]

        audiolog.close()
        padlog.close()

    def join(self):
        self.audio.terminate()
        if self.audio.poll() is None:
            logger.info('good')
        else:
            logger.error('bad')

        self.pad.terminate()
        if self.pad.poll() is None:
            logger.info('good')
        else:
            logger.error('bad')

        super().join()

class DABStreams():
    def __init__(self, config):
        self._srvcfg = config

        self._streamscfg = None
        self._streams = []

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
            logger.info(f'Starting up DAB stream {stream}...')

            try:
                thread = DABStream(self._srvcfg, stream, i, self._streamscfg[stream])
                thread.start()
                self._streams.append((stream, thread))
                i += 1
            except KeyError as e:
                logger.error(f'Unable to start DAB stream "{stream}", check configuration. {e}')
                ret = False
            except OSError as e:
                logger.error(f'Unable to start DAB stream "{stream}". Invalid streams config. {e}')
                ret = False
            except Exception as e:
                logger.error(f'Unable to start DAB stream "{stream}". {e}')
                ret = False

        return ret

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
