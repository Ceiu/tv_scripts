#!/usr/bin/python

"""
Sends commands to and polls status from Sony TVs over RS232.

Requires pyserial (python -m pip install pyserial)
"""

# To any who may be reading this:
#
# There's a lot of ugly code in here. This is intended primarily for myself, so there are many things
# I either didn't document, or could have written out a bit nicer to make reading or future maintenance
# a tad easier. Though, to be honest, it was either this or I'd be using this project as an excuse to write
# something in Rust or Zig; so it could have been so much worse.
#
# I also did not implement every command; only commands for which I have an immediate need, or which piqued
# my interest.
#
#
# Some discovery notes:
#
# Some restrictions that apply specifically to my TV are hard-coded in the command handlers. Specifically,
# the sleep timer is arbitrarily limited in a weird way: rather than accepting any unsigned byte representing
# minutes, it only allows values which are defined in the sleep timer menu. Irritatingly enough, the command
# still requires you represent the target value in minutes. Very odd design choice.
#
# My TV specifically doesn't support the sleep timer "toggle", which I assume to be less of a toggle and
# more cycling through the present values.

# From Sony's docs (https://pro-bravia.sony.net/develop/integrate/rs-232c/index.html):
#
# Interface             RS-232C
# Synchronous Method    Asynchronous
# Baud Rate             9600 bps
# Character Length      8 bits
# Parity                N/A
# Start Bit             1 bit
# Stop Bit              1 bit
# Flow Control          N/A
#







import argparse
import os
import serial
import sys
import time


debug_logging = False

def print_err(errmsg, error_code=1):
    print(errmsg, file=sys.stderr)
    if error_code: exit(error_code)

def print_dbg(msg, *args):
    if debug_logging: print(msg, file=sys.stderr, *args)


def new_serial_connection(device):
    # TODO: perhaps allow CLI configuration of the connection? Probably not that useful in practice.
    conn = serial.Serial(device,
        baudrate=9600,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        # start bits?
        stopbits=serial.STOPBITS_ONE,
        xonxoff=False,
        rtscts=False)

    # May be necessary to deal with certain USB-serial devices when entering or exiting suspend/hibernate
    # Didn't seem to help the random corrupted packets and generally weird behavior I saw.
    # conn.flushInput()
    # conn.flushOutput()

    # time.sleep(0.05)

    return conn

def calculate_checksum(barr):
    return sum(barr) & 0xFF



# Query requests
def validate_query_response(conn):
    # Response to Query Request (Normal End)
    # Byte      Item                Value   Notes
    #   1       Header              0x70    "Answer"
    #   2       Answer              0x00    Completed
    #                                       The packet is received normally and processing is completed
    #                                       normally.
    #                               0x01    Reserved
    #                               0x02    Reserved
    #                               0x03    Command Canceled
    #                                       The request is not acceptable in the current host value, but the
    #                                       packet was received normally.
    #                               0x04    Parse Error (Data Format Error)
    #                                       The packet cannot be received normally, data that was not defined
    #                                       is received, or there is a Check Sum error.
    #   3       Return Data Size    0xXX    N+1 [bytes]
    #                                       The total length between Return Data1 and Check Sum.
    #                                       Return Data returns the read value.
    #   4       Return Data 1       0xXX
    #   :       :                   0xXX
    #   :       :                   0xXX
    #   N+3     Return Data N       0xXX
    #   N+4     Check Sum           0xXX    The total sum from "Byte[1]" to "Byte[N+3]". If it is over 0xFF
    #                                       (1 byte), the last byte of data is used.
    #
    # Response to Query Request (Abnormal End)
    # Byte      Item                Value   Notes
    #   1       Header              0x70    "Answer"
    #   2       Answer              0x03    Command Canceled
    #                                       The packet is received normally, but the request is not acceptable
    #                                       in the current display status.
    #                               0x04    ParseError (Data Format Error)
    #   3       Check Sum           0xXX    Total sum from "Byte[1]" and "Byte[2]".
    #                                       If the value is over 0xFF (1 byte), the last byte of data is used.

    res = bytearray(conn.read(3))

    if res[0] != 0x70:
        print(f"invalid packet received as response: {res.hex()}", file=sys.stderr)
        exit(1)

    if res[1] != 0x00:
        checksum = calculate_checksum(res[0:-1])
        if res[2] != checksum:
            print(f"invalid response packet checksum: {hex(res[2])} != {hex(checksum)}", file=sys.stderr)
            exit(1)

        match res[1]:
            case 0x03:
                print(f"query request failed: command canceled ({hex(res[1])})", file=sys.stderr)
                exit(1)

            case 0x04:
                print(f"query request failed: data format error ({hex(res[1])})", file=sys.stderr)
                exit(1)

            case _:
                print(f"query request failed: unknown error ({hex(res[1])})", file=sys.stderr)
                exit(1)

    res.extend(conn.read(res[2]))
    checksum = calculate_checksum(res[0:-1])

    if res[-1] != checksum:
        print(f"invalid response packet checksum: {hex(res[-1])} != {hex(checksum)}", file=sys.stderr)
        exit(1)

    return res[3:-1]

def query_request(conn, func, data1=0xFF, data2=0xFF):
    # Read Request for Query (PC to BRAVIA Professional Display)
    # Byte      Item        Value   Notes
    #   1       Header      0x83    "Query"
    #   2       Category    0x00
    #   3       Function    0xXX
    #   4       Data[1]     0xFF
    #   5       Data[2]     0xFF
    #   6       Check Sum   0xXX    Total sum from the data "Byte[1]" to the data "Byte[5]".
    #                               If the value is over 0xFF (1 byte), the last byte of data is used.

    req=bytearray(b'\x83\x00')
    req.append(func)
    req.append(data1)
    req.append(data2)
    req.append(calculate_checksum(req))

    print_dbg(f"sending query packet: {req.hex()}")

    conn.write(req)
    return validate_query_response(conn)

def query_input_select(conn, *args):
    res = query_request(conn, 0x02)

    input_map = {
        0x02: lambda i: f"SCART{i}",
        0x03: lambda i: f"Component{i}",
        0x04: lambda i: f"HDMI{i}",
        0x05: lambda i: f"PC",
        0x06: lambda i: f"Shared"
    }

    if res[1] not in input_map:
        return f"Unknown ({hex(res)})"

    return input_map[res[0]](res[1])



# Control requests
def validate_control_response(conn):
    # From Sony's docs (https://pro-bravia.sony.net/develop/integrate/rs-232c/data-format/index.html):
    # Response to Control Request
    #   1   Header      0x70    "Answer"
    #   2   Answer      0x00    Completed (Normal End)
    #                           The packet is received normally and the process is completed normally.
    #                   0x01    Limit Over (Abnormal End – over maximum value)
    #                           The packet is received normally, but the data value exceeds the upper limit.
    #                   0x02    Limit Over (Abnormal End – under minimum value)
    #                           The packet is received normally, but the data value exceeds the lower limit.
    #                   0x03    Command Canceled (Abnormal End)
    #                           The packet is received normally, but either the data is incorrect or the
    #                           request is not acceptable in the current host value.
    #                   0x04    Parse Error (Data Format Error)
    #                           The packet is not received properly (undefined data format) or there is a
    #                           Check Sum error. However, it will be returned as “Limit over” (0x01 or 0x02)
    #                           in that case.
    #   3   Check Sum   0xXX    Total sum from "Byte[1]" to "Byte[2]".

    res = conn.read(3)
    checksum = calculate_checksum(res[0:-1])

    if res[0] != 0x70:
        print_err(f"invalid response packet header: {res.hex()}")

    if res[2] != checksum:
        print_err(f"invalid response packet checksum: {hex(res[2])} != {hex(checksum)}")

    if res[1] != 0x00:
        match res[1]:
            case 0x01:
                print_err(f"control request failed: control value exceeds upper limit ({hex(res[1])})")

            case 0x02:
                print_err(f"control request failed: control value exceeds lower limit ({hex(res[1])})")

            case 0x03:
                print_err(f"control request failed: command canceled ({hex(res[1])})")

            case 0x04:
                print_err(f"control request failed: data format error ({hex(res[1])})")

            case _:
                print_err(f"control request failed: unknown error ({hex(res[1])})")

    return True

def control_request(conn, func, *data):
    # Write Request for Control (PC to BRAVIA Professional Display)
    # Byte      Item        Value   Notes
    #   1       Header      0x8C    "Control"
    #   2       Category    0x00
    #   3       Function    0xXX
    #   4       Length      0xXX    N+1 [bytes].
    #                               Total Length from the data "Data[1]" to the data “Check Sum”.
    #   5       Data[1]     0xXX
    #   :       :           :
    #   N+4     Data[N]     0xXX
    #   N+5     Check Sum   0xXX    Total sum from the "Byte[1]" to the data "Byte[N+4]".
    #                               If the value is over 0xFF (1 byte), the last byte of data is used.

    req=bytearray(b'\x8C\x00')
    req.append(func)
    req.append(len(data) + 1)
    req.extend(data)
    req.append(calculate_checksum(req))

    print_dbg(f"sending control packet: {req.hex()}")

    conn.write(req)
    validate_control_response(conn)

def ctrl_power_state(conn, *args):
    if (len(args) < 1):
        print_err("no power state provided")

    if isinstance(args[0], str):
        pstate = args[0].lower() in ['on', '1']
    else:
        pstate = bool(args[0])

    return control_request(conn, 0x00, int(pstate))

def ctrl_set_volume(conn, *args):
    if (len(args) < 1):
        print_err("no volume level provided")

    if not (isinstance(args[0], int) or (isinstance(args[0], str) and args[0].isnumeric())):
        print_err(f"invalid value provided for volume: {args[0]}")

    volume = int(args[0]) & 0xFF

    return control_request(conn, 0x05, 0x01, volume)

def ctrl_set_sleep_timer(conn, *args):
    if (len(args) < 1):
        print_err("no sleep timer duration provided")

    if not (isinstance(args[0], int) or (isinstance(args[0], str) and args[0].isnumeric())):
        print_err(f"invalid value provided for sleep timer duration: {args[0]}")

    # Note that some TVs (mine) only allow setting the specific values that are listed in the
    # sleep timer menu.
    allowed = [0, 15, 30, 45, 60, 90, 120]
    duration = int(args[0]) & 0xFF

    if not duration in allowed:
        print_err(f"invalid value provided for sleep timer duration; must be one of: {allowed}")

    return control_request(conn, 0x0C, 0x01, duration)


cmd_map = {
    'enable_standby': lambda conn, *args: control_request(conn, 0x01, 0x01),

    'get_power_state': lambda conn, *args: query_request(conn, 0x00)[0],
    'get_input': query_input_select,

    'power_off': lambda conn, *args: ctrl_power_state(conn, (0)),
    'power_on': lambda conn, *args: ctrl_power_state(conn, (1)),
    'display_off': lambda conn, *args: control_request(conn, 0x0D, 0x01, 0x00),
    'display_on': lambda conn, *args: control_request(conn, 0x0D, 0x01, 0x01),

    'get_volume': lambda conn, *args: query_request(conn, 0x05)[1],
    'is_muted': lambda conn, *args: query_request(conn, 0x06)[1],
    'volume_up': lambda conn, *args: control_request(conn, 0x05, 0x00, 0x00),
    'volume_down': lambda conn, *args: control_request(conn, 0x05, 0x00, 0x01),
    'set_volume': ctrl_set_volume,
    'toggle_mute': lambda conn, *args: control_request(conn, 0x06, 0x00),
    'mute': lambda conn, *args: control_request(conn, 0x06, 0x01, 0x01),
    'unmute': lambda conn, *args: control_request(conn, 0x06, 0x01, 0x00),

    'set_sleep_timer': ctrl_set_sleep_timer,
    'clear_sleep_timer': lambda conn, *args: ctrl_set_sleep_timer(conn, (0)),
    'kaboom': lambda conn, *args: query_request(conn, 0x50, 0x01),

    'commands': lambda conn, *args: list(cmd_map.keys())
}


def parse_arguments():
    global debug_logging

    """Parses the arguments provided on the command line"""
    parser = argparse.ArgumentParser(description='Sends commands to Sony TVs over RS232', add_help=True)

    parser.add_argument('--debug', action='store_true', default=False,
        help='Enables debug output')

    parser.add_argument('--device', action='store', default='/dev/ttyUSB0',
        help='The serial device to use to communicate with the target TV; defaults to \'%(default)\'')
    # parser.add_argument('--baud', action='store', type=int, default=9600,
    #     help='The baud rate of the connection; defaults to \'%(default)\'')
    parser.add_argument('cmd', nargs="+", action='store',
        help='The command to execute')

    # TODO: output list of commands as part of the help somehow

    args = parser.parse_args()

    # Set logging level as appropriate
    if args.debug:
        debug_logging = True

    return args

def main():
    args = parse_arguments()

    with new_serial_connection(args.device) as conn:
        command = args.cmd[0].lower()
        if command not in cmd_map:
            print(f"Unknown command: {args.cmd[0]}", file=sys.stderr)
            exit(1)

        output = cmd_map[command](conn, *args.cmd[1:])
        if output is not None: print(output)

if __name__ == '__main__':
    main()
