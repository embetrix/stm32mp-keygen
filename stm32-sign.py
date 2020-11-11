#! /usr/bin/env python3

""" STM32MP Bootloader signing tool

This tool is used to sign bootloader images for STM32MP chips which support
secure boot. Keys can be generated by using:

	openssl ecparam -name prime256v1 -genkey

"""

import logging
import optparse
import sys
import struct
from Cryptodome.Hash import SHA256
from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import DSS

LOG = None

def get_raw_pubkey(key):
	""" Return the binary representation of the X-Y point of the key """
	coord_x_bytes = key.pointQ.x.to_bytes().rjust(32, b'\0')
	coord_y_bytes = key.pointQ.y.to_bytes().rjust(32, b'\0')
	return coord_x_bytes + coord_y_bytes


def unpack_header(image):
	""" Decode an STM32 header into a human-readable dictionary """
	fmt = '<4s64s10I64s83xB'
	fields = struct.unpack(fmt, image[0:256])

	stm32 = {}
	stm32['magic'] = fields[0]
	stm32['signature'] = fields[1]
	stm32['checksum'] = fields[2]
	stm32['hdr_version'] = fields[3]
	stm32['length'] = fields[4]
	stm32['entry_addr'] = fields[5]
	stm32['load_addr'] = fields[7]
	stm32['hdr_version'] = fields[9]
	stm32['option_flags'] = fields[10]
	stm32['ecdsa_algo'] = fields[11]
	stm32['ecdsa_pubkey'] = fields[12]

	return stm32

def repack_header(image, stm32):
	""" Put the data back into an STM32 header """
	fmt = '<4s64s10I64s83xB'
	image[0:256] = struct.pack(fmt,
				   stm32['magic'],
				   stm32['signature'],
				   stm32['checksum'],
				   stm32['hdr_version'],
				   stm32['length'],
				   stm32['entry_addr'],
				   0,
				   stm32['load_addr'],
				   0,
				   stm32['hdr_version'],
				   stm32['option_flags'],
				   stm32['ecdsa_algo'],
				   stm32['ecdsa_pubkey'],
				   0
		)

def key_algorithm(key):
	""" Get the ecdsa algorithm ID for the STM32 header """
	p256_names = ['NIST P-256', 'p256', 'P-256', 'prime256v1', 'secp256r1']
	brainpool_names = []

	if key.curve in p256_names:
		return 1
	if key.curve in brainpool_names:
		return 2

	raise ValueError('Unsupported ECDSA curve "%s"' % key.curve)


def sign_image(image, key):
	""" Sign an image with the given private key """
	stm32 = unpack_header(image)

	if stm32['magic'] != b'STM2':
		LOG.error('Not an STM32 header (signature FAIL)')
		return -1

	stm32['ecdsa_pubkey'] = get_raw_pubkey(key)
	stm32['ecdsa_algo'] = key_algorithm(key)
	stm32['option_flags'] = 0
	repack_header(image, stm32)

	sha = SHA256.new(image[0x48:])
	signatory = DSS.new(key, 'fips-186-3')
	image[0x04:0x44] = signatory.sign(sha)

	verify_signature(image, key)

	LOG.debug('Signature: %s', stm32['signature'].hex())
	return 0

def verify_signature(image, key):
	""" Verify the signature of the binary  """
	hdr = unpack_header(image)
	signature = hdr['signature']
	image_pubkey = hdr['ecdsa_pubkey']
	raw_pubkey = get_raw_pubkey(key)

	if raw_pubkey != image_pubkey:
		print('Image is not signed with the provided key')
		return 1

	sha = SHA256.new(image[0x48:])
	verifier = DSS.new(key, 'fips-186-3')

	try:
		verifier.verify(sha, signature)
		LOG.info('Signature checks out')

	except ValueError:
		LOG.error('The signature is fake news')
		LOG.error('Found:    %s', signature.hex())
		return 2

	return 0


def main():
	""" Bacon wrapper function """
	global LOG
	LOG = logging.getLogger(sys.argv[0])
	LOG.addHandler(logging.StreamHandler())
	parser = optparse.OptionParser()

	parser.add_option('-k', '--key-file', dest='key_file',
			  help='PEM file containing the ECDSA key')

	parser.add_option('-p', '--passphrase', dest='keypass',
			  help='Passphrase for private key, if applicable')

	parser.add_option('-v', '--verbose', dest='verbose', action="store_true",
			  help='Output informative messages')

	parser.add_option('-d', '--debug', dest='debug', action="store_true",
			  help='Output debugging information')

	parser.add_option('-e', '--verify', dest='verify_file',
			  help='Verify signature of STM32 image')

	parser.add_option('-s', '--sign', dest='sign',
			  help='Sign a STM32 image')

	parser.add_option('-o', '--output', dest='outfile',
			  help='Passphrase for private key, if applicable')

	options, _ = parser.parse_args()

	if not options.key_file:
		parser.print_help()
		LOG.error("Must specify a key file")
		return 1

	if options.debug:
		LOG.setLevel(logging.DEBUG)
	elif options.verbose:
		LOG.setLevel('INFO')

	with open(options.key_file) as keyfile:
		key = ECC.import_key(keyfile.read(), passphrase=options.keypass)

	if options.sign:
		if not key.has_private():
			LOG.error('The private key is required for signing')
			return 1

		with open(options.sign, 'rb') as image:
			data = bytearray(image.read())
			sign_image(data, key)

		if options.outfile:
			with open(options.outfile, 'wb') as out:
				out.write(data)

	if options.verify_file:
		try:
			stm32_file = open(options.verify_file, 'rb')
			verify_signature(stm32_file.read(), key)
			return 0
		except OSError as err:
			LOG.error("Can't open %s", options.verify_file)
			return err.errno

	return 0


if __name__ == '__main__':
	sys.exit(main())
