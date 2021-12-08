import configparser # Python INI file parser
import os           # For checking if files exist

class DABStream:
    def __init__(self):
        pass

def dab_streams(config):
    # Load in streams.ini
    stream_config = config['dab']['stream_config']
    os.makedirs(os.path.dirname(stream_config), exist_ok=True)
    self.config = configparser.ConfigParser()
    if os.path.isfile(stream_config):
        self.config.read(stream_config)
    else:
        return None

    pass

