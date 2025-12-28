#!/usr/bin/env python3

"""
Custom SHA3-256 software implementation
Matches hardware's little-endian byte ordering
"""

SHA3_256_RATE = 136

KECCAK_ROUND_CONSTANTS = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808a,
    0x8000000080008000, 0x000000000000808b, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008a,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000a,
    0x000000008000808b, 0x800000000000008b, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800a, 0x800000008000000a, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008
]

def rol64(x, y):
    """64-bit rotate left"""
    return ((x << y) | (x >> (64 - y))) & 0xFFFFFFFFFFFFFFFF

def keccakf_sw(state):
    """Keccak-f[1600] permutation (24 rounds)"""
    for round_idx in range(24):
        # Theta
        bc = [0] * 5
        for i in range(5):
            bc[i] = state[i] ^ state[i + 5] ^ state[i + 10] ^ state[i + 15] ^ state[i + 20]
        for i in range(5):
            t = bc[(i + 4) % 5] ^ rol64(bc[(i + 1) % 5], 1)
            for j in range(0, 25, 5):
                state[j + i] ^= t
        # Rho and Pi
        t = state[1]
        for i in range(24):
            j = [10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4,
                 15, 23, 19, 13, 12, 2, 20, 14, 22, 9, 6, 1][i]
            bc0 = state[j]
            rotc = [1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14,
                    27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44][i]
            state[j] = rol64(t, rotc)
            t = bc0
        # Chi
        for j in range(0, 25, 5):
            bc = [state[j + i] for i in range(5)]
            for i in range(5):
                state[j + i] ^= (~bc[(i + 1) % 5]) & bc[(i + 2) % 5]
        # Iota
        state[0] ^= KECCAK_ROUND_CONSTANTS[round_idx]

def sha3_256_sw(input_data):
    """
    SHA3-256 software implementation
    Uses little-endian byte ordering (matches hardware)
    
    Args:
        input_data: bytes or bytearray to hash
        
    Returns:
        bytes: 32-byte SHA3-256 hash
    """
    state = [0] * 25
    rate_bytes = SHA3_256_RATE
    idx = 0
    length = len(input_data)
    
    # Absorb phase
    while length >= rate_bytes:
        for i in range(rate_bytes // 8):
            word = 0
            for j in range(8):
                if idx < len(input_data):
                    word |= (input_data[idx] << (8 * j))  # Little-endian
                    idx += 1
            state[i] ^= word
        keccakf_sw(state)
        length -= rate_bytes
    
    # Pad and final absorb
    temp = bytearray(rate_bytes)
    for i in range(length):
        if idx < len(input_data):
            temp[i] = input_data[idx]
            idx += 1
    temp[length] = 0x06
    temp[rate_bytes - 1] |= 0x80
    
    for i in range(rate_bytes // 8):
        word = 0
        for j in range(8):
            word |= (temp[i * 8 + j] << (8 * j))  # Little-endian
        state[i] ^= word
    
    keccakf_sw(state)
    
    # Squeeze phase
    output = bytearray(32)
    for i in range(4):
        for j in range(8):
            output[i * 8 + j] = (state[i] >> (8 * j)) & 0xFF  # Little-endian
    
    return bytes(output)

