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

""" List of (European) DAB countries """
# TODO Add support for Africa, Asia, North America
COUNTRY_IDS = {
    'Albania':              (0xE0, 0x9),
    'Algeria':              (0xE0, 0x2),
    'Andorra':              (0xE0, 0x3),
    'Armenia':              (0xE4, 0xA),
    'Austria':              (0xE0, 0xA),
    'Azerbaijan':           (0xE3, 0xB),
    'Azores (Portugal)':    (0xE0, 0x8),
    'Belgium':              (0xE0, 0x6),
    'Belarus':              (0xE3, 0xF),
    'Bosnia Herzegovina':   (0xE4, 0xF),
    'Bulgaria':             (0xE1, 0x8),
    'Canaries (Spain)':     (0xE0, 0xE),
    'Croatia':              (0xE3, 0xC),
    'Cyprus':               (0xE1, 0x2),
    'Czech Republic':       (0xE2, 0x2),
    'Denmark':              (0xE1, 0x9),
    'Egypt':                (0xE0, 0xF),
    'Estonia':              (0xE4, 0x2),
    'Faroe (Denmark)':      (0xE1, 0x9),
    'Finland':              (0xE1, 0x6),
    'France':               (0xE1, 0xF),
    'Georgia':              (0xE4, 0xC),
    'Germany (ECC: 0xD)':   (0xE0, 0xD),
    'Germany (ECC: 0x1)':   (0xE0, 0x1),
    'Gibraltar (UK)':       (0xE1, 0xA),
    'Greece':               (0xE1, 0x1),
    'Hungary':              (0xE0, 0xB),
    'Iceland':              (0xE2, 0xA),
    'Iraq':                 (0xE1, 0xB),
    'Ireland':              (0xE3, 0x2),
    'Israel':               (0xE0, 0x4),
    'Italy':                (0xE0, 0x5),
    'Jordan':               (0xE1, 0x5),
    'Kazakhstan':           (0xE3, 0xD),
    'Kosovo':               (0xE4, 0x7),
    'Kyrgyzstan':           (0xE4, 0x3),
    'Latvia':               (0xE3, 0x9),
    'Lebanon':              (0xE3, 0xA),
    'Libya':                (0xE1, 0xD),
    'Liechtenstein':        (0xE2, 0x9),
    'Lithuania':            (0xE2, 0xC),
    'Luxembourg':           (0xE1, 0x7),
    'Macedonia':            (0xE4, 0x3),
    'Madeira':              (0xE2, 0x8),
    'Malta':                (0xE0, 0xC),
    'Moldova':              (0xE4, 0x1),
    'Monaco':               (0xE2, 0xB),
    'Montenegro':           (0xE3, 0x1),
    'Morocco':              (0xE2, 0x1),
    'Netherlands':          (0xE3, 0x8),
    'Norway':               (0xE2, 0xF),
    'Palestine':            (0xE0, 0x8),
    'Poland':               (0xE2, 0x3),
    'Portugal':             (0xE4, 0x8),
    'Romania':              (0xE1, 0xE),
    'Russian Federation':   (0xE0, 0x7),
    'San Marino':           (0xE1, 0x3),
    'Serbia':               (0xE2, 0xD),
    'Slovakia':             (0xE2, 0x5),
    'Slovenia':             (0xE4, 0x9),
    'Spain':                (0xE2, 0xE),
    'Sweden':               (0xE3, 0xE),
    'Switzerland':          (0xE1, 0x4),
    'Syria':                (0xE2, 0x6),
    'Tajikistan':           (0xE3, 0x5),
    'Tunisia':              (0xE2, 0x7),
    'Turkey':               (0xE3, 0x3),
    'Turkmenistan':         (0xE4, 0xE),
    'Ukraine':              (0xE4, 0x6),
    'United Kingdom':       (0xE1, 0xC),
    'Uzbekistan':           (0xE4, 0xB),
    'Vatican':              (0xE2, 0x4)
}

""" List of (supported) DAB announcement types """
ANNOUNCEMENT_TYPES = {
    'Alarm':        'Alarm announcement (Urgent)',
    'Traffic':      'Road Traffic flash',
    'Travel':       'Public Transport flash',
    'Warning':      'Warning/Service flash (Less urgent than Alarm)',
    'News':         'News flash',
    'Weather':      'Weather bulletin',
    'Event':        'Event announcement',
    'Special':      'Special event',
    # This should actually be Rad_Info according to ETSI, but the name is different in ODR-DabMux's config
    'ProgrammeInfo':'Programme Information',
    'Sports':       'Sport report',
    'Finance':      'Finance report'
}

""" List of supported DAB Programme Type """
# TODO Add support for North American Programme Types
PROGRAMME_TYPES = {
     0: ('None',        'No programme type'),
     1: ('News',        'News'),
     2: ('Affairs',     'Current Affairs'),
     3: ('Info',        'Information'),
     4: ('Sport',       'Sport'),
     5: ('Education',   'Education'),
     6: ('Drama',       'Drama'),
     7: ('Arts',        'Culture'),
     8: ('Science',     'Science'),
     9: ('Talk',        'Varied'),
    10: ('Pop',         'Pop Music'),
    11: ('Rock',        'Rock Music'),
    12: ('Easy',        'Easy Listening Music'),
    13: ('Classics',    'Light Classical'),
    14: ('Classics',    'Serious Classical'),
    15: ('Other_M',     'Other Music'),
    16: ('Weather',     'Weather/meteorology'),
    17: ('Finance',     'Finance/Business'),
    18: ('Children',    'Children\'s programmes'),
    19: ('Factual',     'Social Affairs'),
    20: ('Religion',    'Religion'),
    21: ('Phone_In',    'Phone In'),
    22: ('Travel',      'Travel'),
    23: ('Leisure',     'Leisure'),
    24: ('Jazz',        'Jazz Music'),
    25: ('Country',     'Country Music'),
    26: ('Nation_M',    'National Music'),
    27: ('Oldies',      'Oldies Music'),
    28: ('Folk',        'Folk Music'),
    29: ('Document',    'Documentary')
}
