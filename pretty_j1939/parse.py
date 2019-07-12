#
# Copyright (c) 2019 National Motor Freight Traffic Association Inc. All Rights Reserved.
# See the file "LICENSE" for the full license governing this code.
#

import json
import bitstring

DA_MASK = 0x0000FF00
SA_MASK = 0x000000FF
PF_MASK = 0x00FF0000

j1939db = {}


def init_j1939db():
    global j1939db
    with open("J1939db.json", 'r') as j1939_file:
        j1939db = json.load(j1939_file)


def parse_j1939_id(can_id):
    sa = (SA_MASK & can_id)
    pf = (PF_MASK & can_id) >> 16
    da = (DA_MASK & can_id) >> 8

    if pf >= 240:  # PDU2 format
        pgn = pf * 256 + da
        da = 0xFF
    else:
        pgn = pf * 256
    return pgn, da, sa


def is_connection_management_message(message_id):
    return (message_id & PF_MASK) == 0x00EC0000


def is_data_transfer_message(message_id):
    return (message_id & PF_MASK) == 0x00EB0000


def is_transport_message(message_id):
    return is_data_transfer_message(message_id) or is_connection_management_message(message_id)


def is_bam_cts_message(message_bytes):
    return message_bytes[0] == 32


def get_pgn_acronym(pgn):
    global j1939db
    try:
        acronym = j1939db["J1939PGNdb"]["{}".format(pgn)]["Label"]
        if acronym == '':
            acronym = "Unknown"
        return acronym
    except KeyError:
        return "Unknown"


def get_pgn_name(pgn):
    global j1939db
    try:
        name = j1939db["J1939PGNdb"]["{}".format(pgn)]["Name"]
        if name == '':
            name = get_pgn_acronym(pgn)
        return name
    except KeyError:
        return get_pgn_acronym(pgn)


def get_spn_list(pgn):
    global j1939db
    try:
        return sorted(j1939db["J1939PGNdb"]["{}".format(pgn)]["SPNs"])
    except KeyError:
        return []


def get_spn_name(spn):
    global j1939db
    try:
        return j1939db["J1939SPNdb"]["{}".format(spn)]["Name"]
    except KeyError:
        return "Unknown"


def get_spn_acronym(spn):
    global j1939db
    try:
        return j1939db["J1939SPNdb"]["{}".format(spn)]["Acronym"]
    except KeyError:
        return "Unknown"


def get_address_name(address):
    global j1939db
    try:
        address = "{:3d}".format(address)
        return j1939db["J1939SATabledb"][address.strip()]
    except KeyError:
        return "Unknown"


def get_formatted_address_and_name(address):
    if address == 255:
        formatted_address = "(255)"
        address_name = "All"
    else:
        formatted_address = "({:3d})".format(address)
        try:
            address_name = get_address_name(address)
        except KeyError:
            address_name = "Unknown"
    return formatted_address, address_name


def describe_message_id(message_id):
    description = {}

    pgn, da, sa = parse_j1939_id(message_id)
    pgn_acronym = get_pgn_acronym(pgn)
    da_formatted_address, da_address_name = get_formatted_address_and_name(da)
    sa_formatted_address, sa_address_name = get_formatted_address_and_name(sa)

    description['PGN'] = "%s(%s)" % (pgn_acronym, pgn)
    description['DA'] = "%s%s" % (da_address_name, da_formatted_address)
    description['SA'] = "%s%s" % (sa_address_name, sa_formatted_address)
    return description


def lookup_all_spn_params(callback, spn):
    global j1939db

    # look up items in the database
    name = get_spn_name(spn)
    units = j1939db["J1939SPNdb"]["{}".format(spn)]["Units"]
    spn_start = j1939db["J1939SPNdb"]["{}".format(spn)]["StartBit"]
    spn_end = j1939db["J1939SPNdb"]["{}".format(spn)]["EndBit"]
    spn_length = j1939db["J1939SPNdb"]["{}".format(spn)]["SPNLength"]
    offset = j1939db["J1939SPNdb"]["{}".format(spn)]["Offset"]
    scale = j1939db["J1939SPNdb"]["{}".format(spn)]["Resolution"]
    if scale <= 0:
        scale = 1
    return name, offset, scale, spn_end, spn_length, spn_start, units


def get_spn_bytes(message_data, spn):
    spn_start = j1939db["J1939SPNdb"]["{}".format(spn)]["StartBit"]
    spn_end = j1939db["J1939SPNdb"]["{}".format(spn)]["EndBit"]

    cut_data = bitstring.BitString(message_data)[spn_start:spn_end + 1]
    cut_data.byteswap()

    return cut_data


def is_spn_bitencoded(spn_units):
    return spn_units.lower() in ("bit", "binary",)


def is_spn_numerical_values(spn):
    spn_units = j1939db["J1939SPNdb"]["{}".format(spn)]["Units"]
    norm_units = spn_units.lower()
    return norm_units not in ("manufacturer determined", "byte", "", "request dependent", "ascii")


# returns a float in units of the SPN, or None if the value if the SPN value is not available in the message_data
#   if validate == True, raises a ValueError if the value is present in message_data but is beyond the operational range
def get_spn_value(message_data, spn, validate=True):
    units = j1939db["J1939SPNdb"]["{}".format(spn)]["Units"]

    offset = j1939db["J1939SPNdb"]["{}".format(spn)]["Offset"]
    scale = j1939db["J1939SPNdb"]["{}".format(spn)]["Resolution"]
    if scale <= 0:
        scale = 1

    cut_data = get_spn_bytes(message_data, spn)
    if cut_data.all(True):  # value unavailable in message_data
        return None

    if is_spn_bitencoded(units):
        value = cut_data.uint
    else:
        value = cut_data.uint * scale + offset

        if validate:
            operational_min = j1939db["J1939SPNdb"]["{}".format(spn)]["OperationalLow"]
            operational_max = j1939db["J1939SPNdb"]["{}".format(spn)]["OperationalHigh"]
            if value < operational_min or value > operational_max:
                raise ValueError

    return value


def describe_message_data(message_id, message_data, include_na=False):
    pgn, da, sa = parse_j1939_id(message_id)

    description = dict()
    for spn in get_spn_list(pgn):
        spn_name = get_spn_name(spn)
        spn_units = j1939db["J1939SPNdb"]["{}".format(spn)]["Units"]

        try:
            if is_spn_numerical_values(spn):
                spn_value = get_spn_value(message_data, spn)
                if spn_value is None:
                    if include_na:
                        description[spn_name] = "N/A"
                    else:
                        continue
                elif is_spn_bitencoded(spn_units):
                    try:
                        enum_descriptions = j1939db["J1939BitDecodings"]["{}".format(spn)]
                        spn_value_description = enum_descriptions[str(int(spn_value))].strip()
                        description[spn_name] = "%d (%s)" % (spn_value, spn_value_description)
                    except KeyError:
                        description[spn_name] = "%d (Unknown)" % spn_value
                else:
                    description[spn_name] = "%s (%s)" % (spn_value, spn_units)
            else:
                if spn_units.lower() in ("request dependent",):
                    description[spn_name] = "%s (%s)" % (get_spn_bytes(message_data, spn), spn_units)
                elif spn_units.lower() in ("ascii",):
                    description[spn_name] = "%s" % get_spn_bytes(message_data, spn).tobytes()
                else:
                    description[spn_name] = "%s" % get_spn_bytes(message_data, spn)

        except ValueError:
            description[spn_name] = "%s (%s)" % (get_spn_bytes(message_data, spn), "Out of range")

    return description


def describe_data_transfer_complete(message_data, sa, pgn, timestamp):
    description = dict()

    description['PGN'] = pgn
    description['data'] = str(bitstring.BitString(message_data))

    return description


def get_bam_processor(process_bam_found):
    new_pgn = {}
    new_data = {}
    new_packets = {}
    new_length = {}

    def process_for_bams(message_bytes, message_id, sa, timestamp):
        if is_connection_management_message(message_id):
            if is_bam_cts_message(message_bytes):  # BAM,CTS
                new_pgn[sa] = (message_bytes[7] << 16) + (message_bytes[6] << 8) + message_bytes[5]
                new_length[sa] = (message_bytes[2] << 8) + message_bytes[1]
                new_packets[sa] = message_bytes[3]
                new_data[sa] = [0xFF for i in range(7 * new_packets[sa])]

        elif is_data_transfer_message(message_id):
            # print("{:08X}".format(message_id) + "".join(" {:02X}".format(d) for d in message))
            if sa in new_data.keys():
                for b, i in zip(message_bytes[1:], range(7)):
                    try:
                        new_data[sa][i + 7 * (message_bytes[0] - 1)] = b
                    except Exception as e:
                        print(e)
                if message_bytes[0] == new_packets[sa]:
                    data_bytes = bytes(new_data[sa][0:new_length[sa]])
                    process_bam_found(data_bytes, sa, new_pgn[sa], timestamp)

    return process_for_bams
