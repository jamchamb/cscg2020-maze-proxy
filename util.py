import random


def xorb(a, b):
    return chr(ord(a) ^ ord(b))


def decrypt_data(data):

    key_x = ord(data[0])
    key_y = ord(data[1])

    decrypted = [ord(x) for x in data]

    for i in range(2, len(data)):
        decrypted[i] = ord(data[i]) ^ key_x
        new_key = key_x + key_y
        key_x = (new_key + (new_key / 0xff)) & 0xff

    return ''.join([chr(x) for x in decrypted])


def encrypt_data(data, fast=False):

    if fast:
        return '\x00\x00' + data

    key_x = random.randint(0, 255)
    key_y = random.randint(0, 255)

    encrypted = [key_x, key_y] + [0 for x in data]

    for i in range(len(data)):
        encrypted[i + 2] = ord(data[i]) ^ key_x
        new_key = key_x + key_y
        key_x = (new_key + (new_key / 0xff)) & 0xff

    return ''.join([chr(x) for x in encrypted])
