#! /usr/bin/env python3

""" STM32MP Bootloader signing tool using pkcs11 token

This tool is used to sign bootloader images for STM32MP chips which support
secure boot. Keys can be generated by using:

	pkcs11-tool --keypairgen --key-type EC:prime256v1 --label "key6892" --id key6892  --login --usage-sign  --module /usr/lib/softhsm/libsofthsm2.so

"""

import os
import logging
import optparse
import sys
import struct
import pkcs11
from Crypto.Hash import SHA256
from Crypto.PublicKey import ECC
from Crypto.Signature import DSS
from pkcs11 import KeyType, ObjectClass, Mechanism
from pkcs11.util.ec import encode_ec_public_key

LOG = None

def get_raw_pubkey(pubkey):
	""" Return the binary representation of the X-Y point of the key """
	pkey = ECC.import_key(encode_ec_public_key(pubkey))
	coord_x_bytes = pkey.pointQ.x.to_bytes().rjust(32, b'\0')
	coord_y_bytes = pkey.pointQ.y.to_bytes().rjust(32, b'\0')
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
	stm32['rollback_version'] = fields[9]
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
				   stm32['rollback_version'],
				   stm32['option_flags'],
				   stm32['ecdsa_algo'],
				   stm32['ecdsa_pubkey'],
				   0
		)

def key_algorithm(pubkey):
	""" Get the ecdsa algorithm ID for the STM32 header """
	pkey = ECC.import_key(encode_ec_public_key(pubkey))
	""" Get the ecdsa algorithm ID for the STM32 header """
	p256_names = ['NIST P-256', 'p256', 'P-256', 'prime256v1', 'secp256r1']
	brainpool_names = []

	if pkey.curve in p256_names:
		return 1
	if pkey.curve in brainpool_names:
		return 2

	raise ValueError('Unsupported ECDSA curve "%s"' % pkey.curve)


def pkcs11_sign_image(image, module_path, token, key_label, pin):
	""" Sign an image with the given private key """
	stm32 = unpack_header(image)

	if stm32['magic'] != b'STM2':
		LOG.error('Not an STM32 header (signature FAIL)')
		return -1

	lib = pkcs11.lib(module_path)
	token = lib.get_token(token_label=token)
	with token.open(rw=True, user_pin=pin) as session:
		privkey   = session.get_key(label=key_label, key_type=KeyType.EC, object_class=ObjectClass.PRIVATE_KEY)
		pubkey    = session.get_key(label=key_label, key_type=KeyType.EC, object_class=ObjectClass.PUBLIC_KEY)

		stm32['ecdsa_pubkey'] = get_raw_pubkey(pubkey)
		stm32['ecdsa_algo']   = key_algorithm(pubkey)
		stm32['option_flags'] = 0
		repack_header(image, stm32)
		sha = SHA256.new(image[0x48:]).digest()
		signature = privkey.sign(sha, mechanism=Mechanism.ECDSA)
		image[0x04:0x44] = signature

	LOG.debug('Signature: %s', signature.hex())
	return 0

def pkcs11_verify_signature(image, module_path, token, key_label, pin):
	""" Verify the signature of the binary  """
	hdr = unpack_header(image)
	signature = hdr['signature']
	image_pubkey = hdr['ecdsa_pubkey']

	lib = pkcs11.lib(module_path)
	token = lib.get_token(token_label=token)
	with token.open(rw=True, user_pin=pin) as session:
		pubkey = session.get_key(label=key_label, key_type=KeyType.EC, object_class=ObjectClass.PUBLIC_KEY)
		sha = SHA256.new(image[0x48:])
		verifier = DSS.new(ECC.import_key(encode_ec_public_key(pubkey)), 'fips-186-3')

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

	parser.add_option('-m', '--module-path', dest='module_path',
			  help='PKCS11 module path')

	parser.add_option('-t', '--token', dest='token',
			  help='PKCS11 token')
	
	parser.add_option('-l', '--key-label', dest='key_label',
			  help='PKCS11 key label')
	
	parser.add_option('-p', '--pin', dest='pin',
			  help='Pin for Token if applicable')

	parser.add_option('-V', '--verbose', dest='verbose', action="store_true",
			  help='Output informative messages')

	parser.add_option('-d', '--debug', dest='debug', action="store_true",
			  help='Output debugging information')

	parser.add_option('-v', '--verify', dest='verify_file',
			  help='Verify signature of STM32 image')

	parser.add_option('-s', '--sign', dest='sign',
			  help='Sign a STM32 image')

	parser.add_option('-o', '--output', dest='outfile',
			  help='Output Signed file')

	options, _ = parser.parse_args()

	if not options.module_path:
		parser.print_help()
		LOG.error("Must specify pkcs11 module path")
		return 1

	if not options.token:
		parser.print_help()
		LOG.error("Must specify pkcs11 token")
		return 1

	if not options.key_label:
		parser.print_help()
		LOG.error("Must specify pkcs11 key label")
		return 1

	if options.debug:
		LOG.setLevel(logging.DEBUG)
	elif options.verbose:
		LOG.setLevel('INFO')

	if options.sign:

		with open(options.sign, 'rb') as image:
			data = bytearray(image.read())
			pkcs11_sign_image(data, options.module_path, options.token, options.key_label, options.pin)

		if options.outfile:
			with open(options.outfile, 'wb') as out:
				out.write(data)

	if options.verify_file:
		try:
			stm32_file = open(options.verify_file, 'rb')
			pkcs11_verify_signature(stm32_file.read(), options.module_path, options.token, options.key_label, options.pin)
			return 0
		except OSError as err:
			LOG.error("Can't open %s", options.verify_file)
			return err.errno

	return 0


if __name__ == '__main__':
	sys.exit(main())