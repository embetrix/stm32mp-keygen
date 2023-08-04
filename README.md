# stm32mp-keygen

A key generation utility for STM32MP SOCs.

## Generating keys

This package does not provide an explicit method of generating ECDSA keys. Keys
can be generated with the __openssl__ package:

	$ openssl ecparam -name prime256v1 -genkey -out <private_key.pem>
	$ openssl ec -in <private_key.pem> -pubout -out <public_key.pem>

For PKCS11 keys can be generated with the __pkcs11-tool__ package:

	$ pkcs11-tool --module <pkcs11 module path> --keypairgen --key-type EC:prime256v1 --id <key id> --label <key label> --login --usage-sign

or imported  with the __pkcs11-tool__ package:

	$ pkcs11-tool --module <pkcs11 module path>  --login  --write-object <private_key.der> --type privkey --id <key id> --label <key label>  --usage-sign
	$ pkcs11-tool --module <pkcs11 module path>  --login  --write-object <public_key.der>  --type pubkey  --id <key id> --label <key label>  --usage-sign
	$ pkcs11-tool --module <pkcs11 module path>  --login  --read-object --type pubkey --id <key id>  | openssl ec -pubin  -pubout -outform PEM -out <public_key.pem>

### Generating the key hashes

In order to be used by the STM32MP secure boot, the public key must be hashed.
The __ecdsa-sha256.py__ is provided for this purpose:

	$ ./ecdsa-sha256.py --public-key=<public_key.pem> --binhash-file=<hash.bin>

## Signing and verifying images

STM32 images can be checked and signed with __stm32-sign.py__. Note that images
must already have an STM32 header (e.g. u-boot-spl.stm32).

	$ ./stm32-sign.py --help
	$ ./stm32-sign.py --key-file <public_key.pem> --verify <image.stm32>

To sign an STM32 image:

	$ ./stm32-sign.py --key-file <private_key.pem> --sign <image.stm32> --output <image-signed.stm32>


## PKCS11 Signing and verifying images 

STM32 images can be checked and signed with __stm32-sign-pkcs11.py__. Note that images
must already have an STM32 header (e.g. u-boot-spl.stm32).

To sign an STM32 image with PKCS11:

	$ ./stm32-sign-pkcs11.py --help
	$ ./stm32-sign-pkcs11.py  -m <pkcs11 module path> -t <token> -l <key label>  -s <image.stm32> -p <pin> -o <image.stm32.sign>

To verify an STM32 image with PKCS11:

	$ ./stm32-sign-pkcs11.py  -m <pkcs11 module path> -t <token> -l <key label>  -v <image.stm32.sign> -p <pin>

## Developer tools

### Testing utilities

#### Binary hash testing

The hash generation can be tested with __tests/test_keyhash.sh__. This tool
compares the output of the key hashing utility to the _official_ STM tool. It
marks failing hashes for further analysis.

	$ tests/test_keyhash.sh

It can be massaged with the following environment variables:

  * __STM_KEYGEN_BIN__ - Location __STM32MP_KeyGen_CLI__ binary
  * __KEYHASH_BIN__ - Location of __ecdsa-sha256.py__ tool
