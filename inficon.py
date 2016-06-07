#!/usr/bin/env python
'''
Implement the Inficon protocol for retrieving gauge status. Errors are written to STDERR (not logged).
'''

# The default serial port is /dev/ttyUSB0, which is typically the first USB serial device.

# If you're using an on-board RS232 port, you will want to use eg. /dev/ttyS0

# If you are using a USB to serial dongle, you'll need the correct device name. To list all available ports on your system, try:

#   $ python -m serial.tools.list_ports

# Common serial names include:
#  * /dev/cu.PL2303-*
#  * /dev/cu.UC-232AC
#  * /dev/ttyAMA0 (Raspberry Pi)

import serial
import sys
import os
import re
import datetime
import argparse
from time import sleep

opts = {
	'port': 		{ 'value': '/dev/ttyUSB0', 'help': 'serial port', 'type': str },
	'baudrate':		{ 'value': 9600, 'help': 'serial baud rate', 'type': int },
	'databits':		{ 'value': 8, 'help': 'data bits', 'type': int },
	'parity':		{ 'value': 'N', 'help': 'parity', 'type': str },
	'stopbits':		{ 'value': 1, 'help': 'stop bits', 'type': int },
	'timeout':		{ 'value': 5, 'help': 'serial timeout', 'type': int },
	'softflow':		{ 'value': False, 'help': 'software flow control', 'type': bool },
	'hardflow':		{ 'value': False, 'help': 'hardware flow control', 'type': bool },
	'log':			{ 'value': 'STDOUT', 'help': 'Log file to append to. STDOUT writes to the console.', 'type': str },
	'interactive':	{ 'value': False, 'help': 'Interactive mode. Prompts for INFICON commands and returns any reply.', 'type': bool },
	'poll':			{ 'value': 60, 'help': 'Seconds to wait between polls', 'type': int },
	'oneshot':		{ 'value': False, 'help': 'Poll all sensors once and exit', 'type': bool },
	'gauges':		{ 'value': '0,1', 'help': 'Comma-separated list of ports to poll', 'type': str },
}

STX = chr(2)

def get_terminal_width(margin=5):
	'''
	Return the current terminal width minus a nice margin.

	In python 3.3+, use shutil.get_terminal_size() instead.
	'''
	if not sys.stdout.isatty():
		return 80

	import struct
	from fcntl import ioctl
	from termios import TIOCGWINSZ
	reply = ioctl(sys.stdout, TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
	return struct.unpack("HHHH", reply)[0:2][1] - margin

def checksum(line):
	''' Inficon checksum algorithm '''
	chk = 0
	for char in line:
		chk += ord(char)
	return chr(chk & 255)

def send(port, cmd):
	''' Send a single line, with checksum. '''
	try:
		port.write(STX + chr(len(cmd)) + cmd + str(checksum(cmd)))
	except serial.SerialTimeoutException:
		sys.stderr.write('%s: serial timeout sending command: %s'.format(str(datetime.datetime.now()), cmd))

def receive(port, retries=5):
	''' Receive up to one full response message. Returns the message or an appropriate error. '''
	start = None
	attempt = 1
	# Skip anything that isn't STX
	while start != STX:
		start = port.read(1)

		if start != STX and attempt > retries:
			sys.stderr.write('Timeout while waiting for STX\n')
			return ''

		attempt += 1

	# Next byte is size
	size = ord(port.read(1))

	# Read size data bytes
	data = port.read(size)

	if len(data) != size:
		sys.stderr.write('%s: serial timeout while receiving data: %s'.format(str(datetime.datetime.now()), data))
		return ''

	# Grab the checksum
	chk = port.read(1)

	if chk == checksum(data):
		return data
	else:
		sys.stderr.write('Invalid message: ' + data + '\n')

if __name__ == '__main__':

	# argparse foolishly relies on the COLUMNS environment variable to determine the terminal width.
	# This is only used in Bash-like shells, and even then it isn't exported by default, so argparse
	# defaults to a paltry 80 columns.
	#
	# This gets the real terminal width if COLUMNS isn't already available.
	if not 'COLUMNS' in os.environ:
		os.environ['COLUMNS'] = str(get_terminal_width())

	# Build out a dynamic argument list based on opts
	PARSER = argparse.ArgumentParser(description=__doc__)
	for opt in opts:
		this_type = opts[opt]['type']
		this_val = this_type(opts[opt]['value'])

		if this_type == bool:
			action = 'store_false' if this_val == True else 'store_true'
			PARSER.add_argument(
				'--' + opt,
				default=this_val,
				action=action,
				help='%s (default: %s)' % (opts[opt]['help'], str(this_val))
			)
		else:
			PARSER.add_argument(
				'--' + opt,
				default=this_val,
				type=this_type,
				action='store',
				help='%s (default: %s)' % (opts[opt]['help'], str(this_val))
			)

	ARGS = PARSER.parse_args()

	# Gauge sanity check
	gauges = ARGS.gauges.split(',')
	for gauge in gauges:
		try:
			assert int(gauge) in range(10)
		except ValueError:
			print 'Invalid gauge: ' + gauge
			sys.exit(1)
		except AssertionError:
			print 'Invalid gauge %s (should be 0-9)' % gauge
			sys.exit(1)

	# Write to STDOUT, or append to the specified log.
	print 'datetime,' + ARGS.gauges
	if ARGS.log == 'STDOUT':
		log = sys.stdout
	else:
		log = open(ARGS.log, 'a', 0)
		# Add a nice CSV header if appropriate.
		if log.tell() == 0:
			log.write('datetime,' + ARGS.gauges + '\n')

	ser = serial.Serial(
		port=ARGS.port,
		baudrate=ARGS.baudrate,
		bytesize=ARGS.databits,
		parity=ARGS.parity,
		stopbits=ARGS.stopbits,
		timeout=ARGS.timeout,
		xonxoff=ARGS.softflow,
		rtscts=ARGS.hardflow,
		# dsrdtr follows rtscts
		dsrdtr=None
	)

	# Until ^C
	while True:
		try:
			if ARGS.interactive:
				send(ser, raw_input('> ').rstrip())
				print receive(ser)

			else:
				readings = []
				for gauge in gauges:
					send(ser, "S0" + gauge)
					match = re.match(r"(.*-\d+)", receive(ser))
					if(match):
						readings.append(match.group(1))
					else:
						readings.append('')

				msg = ','.join([str(datetime.datetime.now())] + readings)
				print msg
				log.write(msg + "\n")

				if ARGS.oneshot:
					sys.exit(0)

				sleep(ARGS.poll)

		except (KeyboardInterrupt, EOFError):
			print
			sys.exit(0)
