#!/usr/bin/env python3

import sys
from pathlib import Path
# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from migen import *
from migen.sim import run_simulation
from keccak_datapath_simd import KeccakDatapath
import hashlib
from VerificationTest.sha3_function import sha3_256_sw

def test_sha3_validity():
    print("--- SHA3 Validity Test ---")
    
    dut = KeccakDatapath(MAX_BLOCKS=4, MAX_DIFFICULTY_BITS=128)

    def generator():
        # ======================================================
        # TEST 1: Hash Validity Test
        # ======================================================
        print("\n[TEST 1] Hash Validity Test")
        
        # Create 100-byte test input with a repeating pattern
        test_input_bytes = bytearray()
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        for i in range(100):
            test_input_bytes.append(pattern[i % len(pattern)])
        
        test_input_bytes[1] = 32
        for i in range(2, 34):
            test_input_bytes[i] = 0
        
        # --- FIX 1: Load input as LITTLE ENDIAN ---
        # SHA3 reads the input stream as little-endian words.
        # This ensures Byte 0 maps to Bits[0:8] of the header_data signal.
        test_input = int.from_bytes(test_input_bytes, 'little')
        
        print("\nInput Data Structure:")
        print(f"  First 8 bytes (Hex): {test_input_bytes[0:8].hex()}")
        
        yield dut.input_length.eq(100)
        yield dut.target.eq(0x0FFFFFFFFFFFFFFF) 
        yield dut.header_data.eq(test_input)

        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        yield

        cycle_count = 0
        found_status = 0
        
        while (yield dut.running):
            cycle_count += 1
            found_status = yield dut.found
            
            # Check every 27 cycles
            if cycle_count % 27 == 0:
                state_0_full = yield dut.state_0
                
                # Extract bottom 256 bits (SHA3-256 output)
                HASH_BITS = 256
                state_0_256 = state_0_full & ((1 << HASH_BITS) - 1)
                
                print(f"\n  [Cycle {cycle_count}] State check:")
                print(f"    state_0[0:{HASH_BITS}]: 0x{state_0_256:064x}")
                
                current_nonce_0 = yield dut.nonce_0
                expected_data = bytearray(test_input_bytes)
                
                # --- FIX 2: Convert Nonce to LITTLE ENDIAN bytes ---
                # The hardware injects the nonce LSB at the lowest bit index.
                # This corresponds to Little Endian byte ordering.
                nonce_0_bytes = current_nonce_0.to_bytes(30, byteorder='little')
                
                expected_data[4:34] = nonce_0_bytes
                
                # Calculate expected hash using custom software function
                # Note: sha3_256_sw handles the little-endian conversion internally
                expected_hash_sw = sha3_256_sw(expected_data)
                expected_hash_sw_int = int.from_bytes(expected_hash_sw, byteorder='little')
                
                # Calculate expected hash using library (for double verification)
                hash_obj = hashlib.sha3_256()
                hash_obj.update(expected_data)
                expected_hash_lib = hash_obj.digest()
                # Note: hashlib returns bytes. To compare with our Little Endian signal state,
                # we must interpret the library output bytes as Little Endian integer.
                expected_hash_lib_int = int.from_bytes(expected_hash_lib, byteorder='little')

                print(f"    nonce_0: 0x{current_nonce_0:060x}")
                print(f"    Expected (Lib LE): 0x{expected_hash_lib_int:064x}")
                print(f"    Actual (HW):       0x{state_0_256:064x}")
                
                if state_0_256 == expected_hash_lib_int:
                    print(f"    ✓ Core 0 hash MATCHES expected value!")
                else:
                    print(f"    ✗ Core 0 hash mismatch")
            
            if found_status != 0:
                yield
                break
            yield

    run_simulation(dut, generator())

if __name__ == "__main__":
    test_sha3_validity()