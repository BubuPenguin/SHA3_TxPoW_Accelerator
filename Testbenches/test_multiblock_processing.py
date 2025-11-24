#!/usr/bin/env python3

from migen import *
from migen.sim import run_simulation
from keccak_datapath_simd import KeccakDatapath
import hashlib
from sha3_function import sha3_256_sw

def test_multiblock_processing():
    print("--- Multi-Block Processing Test ---")
    
    dut = KeccakDatapath(MAX_BLOCKS=4, MAX_DIFFICULTY_BITS=128)

    def generator():
        print("\n[TEST 1] Hash Validity Test (300 Bytes / 3 Blocks)")
        
        # 1. Setup Input Data (300 Bytes)
        test_input_bytes = bytearray()
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        for i in range(300):
            test_input_bytes.append(pattern[i % len(pattern)])
        
        test_input_bytes[1] = 32 # Length
        for i in range(2, 34):   # Clear Nonce
            test_input_bytes[i] = 0
        
        # 2. Load as LITTLE ENDIAN
        test_input = int.from_bytes(test_input_bytes, 'little')
        
        EXPECTED_BLOCKS = (len(test_input_bytes) // 136) + 1
        print(f"  Input Size: {len(test_input_bytes)} bytes")
        print(f"  Python Calc Blocks: {EXPECTED_BLOCKS}")

        yield dut.input_length.eq(300)
        
        # --- FIX: Set Target to MAX (Always Succeed) ---
        # This prevents the hardware from incrementing the nonce and looping.
        # It will stop in the IDLE state with Nonce=1 and Hash=Hash(Nonce 1).
        yield dut.target.eq(2**128 - 1) 
        
        yield dut.header_data.eq(test_input)

        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        yield

        cycle_count = 0
        verified = False
        
        while (yield dut.running) or (yield dut.found) != 0:
            cycle_count += 1
            
            # Check if we found a "solution" (which we will, because target is easy)
            found_status = yield dut.found
            
            if found_status != 0 and not verified:
                # Wait one cycle for signals to settle if needed, or read immediately
                state_0_full = yield dut.state_0
                
                # Extract SHA3-256 (Bottom 256 bits)
                HASH_BITS = 256
                state_0_256 = state_0_full & ((1 << HASH_BITS) - 1)
                
                print(f"\n  [Cycle {cycle_count}] Hash 'Found' (Target Met). Verifying...")
                
                # Reconstruct expected data
                current_nonce_0 = yield dut.nonce_0
                expected_data = bytearray(test_input_bytes)
                nonce_0_bytes = current_nonce_0.to_bytes(30, byteorder='little')
                expected_data[4:34] = nonce_0_bytes
                
                # Calculate Expected Hash (Library)
                hash_obj = hashlib.sha3_256()
                hash_obj.update(expected_data)
                expected_hash_lib = hash_obj.digest()
                expected_hash_lib_int = int.from_bytes(expected_hash_lib, byteorder='little')
                
                print(f"    Nonce:         0x{current_nonce_0:060x}")
                print(f"    Expected (LE): 0x{expected_hash_lib_int:064x}")
                print(f"    Actual   (HW): 0x{state_0_256:064x}")
                
                if state_0_256 == expected_hash_lib_int:
                    print(f"    ✓ SUCCESS: Multi-block hash matches.")
                else:
                    print(f"    ✗ FAILURE: Hash mismatch.")
                
                verified = True
                break 

            # Watchdog
            if cycle_count > 200:
                print("  [TIMEOUT] Simulation ran too long.")
                break
            
            yield

    run_simulation(dut, generator())

if __name__ == "__main__":
    test_multiblock_processing()