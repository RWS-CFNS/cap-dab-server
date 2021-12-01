#!/usr/bin/env python3

from dialog import Dialog   # Beautiful dialogs using the external program dialog
import threading            # Threading support (for running Flask in the background)
import logging              # Logging facilities

import sys
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

from cap.server import cap_server

# TODO add to command line parameters
logging.basicConfig(filename='server.log', level=logging.DEBUG)
debug = False
strict = False
host = '127.0.0.1'
port = 5000
# TODO take a textfile with a list of accepted senders as input

d = Dialog(dialog='dialog')

#def config():
    #

def log():
    d.textbox('server.log', height=0, width=0, no_shadow=True)

def main():
    while True:
        #code, tag = d.menu('Main menu', title='CAP-DAB Server Admin Interface', choices=[
        #                  ('Config', 'Configure radio streams'),
        #                  ('Log',     'View the server log'),
        #                  ('Stop',    'Stop the server and exit')])
        code, tag = d.menu('Main menu', title='CAP-DAB Server Admin Interface', choices=[
                          ('Config', 'Configure radio streams'),
                          ('Log',     'View the server log'),
                          ('Stop',    'Stop the server and exit')])

        # TODO check exit codes (https://pythondialog.sourceforge.io/doc/Dialog_class_overview.html#return-value-of-widget-producing-methods)

        # don't bother doing this fancy, the menu is not that large anyways
        if tag == 'Config':
            config()
        if tag == 'Log':
            log()
        elif tag == 'Stop':
            break

if __name__ == '__main__':
    # FIXME don't use daemon and try using events to stop Flask
    threading.Thread(target=cap_server, args=(host, port, debug, strict), daemon=True).start()

    d.set_background_title('© 2021 Rijkswaterstaat-CIV CFNS')

    main()
