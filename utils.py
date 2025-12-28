#!/usr/bin/env python3

#
# User Accelerator Utilities
# 
# Shared constants and utility functions for accelerator modules
#

KECCAK_ROUND_CONSTANTS = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

RHO_OFFSETS = [
    [0, 1, 62, 28, 27],
    [36, 44, 6, 55, 20],
    [3, 10, 43, 25, 39],
    [41, 45, 15, 21, 8],
    [18, 2, 61, 56, 14],
]

# Byte masks for partial word masking (0-8 bytes)
# Used for masking unused bytes in 64-bit word reads
BYTE_MASKS = [
    0x0000000000000000,  # 0 bytes
    0x00000000000000FF,  # 1 byte
    0x000000000000FFFF,  # 2 bytes
    0x0000000000FFFFFF,  # 3 bytes
    0x00000000FFFFFFFF,  # 4 bytes
    0x000000FFFFFFFFFF,  # 5 bytes
    0x0000FFFFFFFFFFFF,  # 6 bytes
    0x00FFFFFFFFFFFFFF,  # 7 bytes
    0xFFFFFFFFFFFFFFFF,  # 8 bytes
]


def rol64(value, shift):
    """Rotate left 64-bit value by shift bits."""
    if shift == 0:
        return value
    return ((value << shift) | (value >> (64 - shift)))[:64]

