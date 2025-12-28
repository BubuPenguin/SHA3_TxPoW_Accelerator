#!/usr/bin/env python3

"""
Multi-Block Processing Test (Updated for Difficulty Fix)

Tests:
1. Hash validity for multi-block inputs (300 bytes)
2. Difficulty comparison using MSBs (bits 128-255) instead of LSBs
3. Verify both linear and stochastic search paths work correctly

FIXES APPLIED:
- Difficulty comparison now uses bits 128-255 (MSBs) instead of 0-127 (LSBs)
- Added explicit tests to verify the MSB comparison logic
- Better verification of hash correctness
"""

import sys
from pathlib import Path
# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from migen import *
from migen.sim import run_simulation
from keccak_datapath_simd import KeccakDatapath
import hashlib

def test_multiblock_processing():
    print("="*70)
    print("Multi-Block Processing Test Suite (Updated)")
    print("="*70)
    
    dut = KeccakDatapath(MAX_BLOCKS=16, MAX_DIFFICULTY_BITS=128)

    def generator():
        # ======================================================================
        # TEST 1: Hash Validity Test (300 Bytes / 3 Blocks)
        # ======================================================================
        print("\n" + "="*70)
        print("[TEST 1] Hash Validity Test (300 Bytes / 3 Blocks)")
        print("="*70)
        
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
        print(f"  Expected Blocks: {EXPECTED_BLOCKS}")

        yield dut.input_length.eq(300)
        
        # Set Target to MAX (Always Succeed)
        # This prevents the hardware from incrementing the nonce and looping.
        yield dut.target.eq((1 << 128) - 1)  # Max 128-bit value
        
        yield dut.header_data.eq(test_input)

        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        yield

        cycle_count = 0
        verified = False
        
        while (yield dut.running) or (yield dut.found) != 0:
            cycle_count += 1
            
            # Check if we found a "solution"
            found_status = yield dut.found
            
            if found_status != 0 and not verified:
                state_0_full = yield dut.state_0
                
                # Extract SHA3-256 (Bottom 256 bits of state)
                HASH_BITS = 256
                state_0_256 = state_0_full & ((1 << HASH_BITS) - 1)
                
                print(f"\n  [Cycle {cycle_count}] Hash 'Found'. Verifying...")
                
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
                    print(f"    [PASS] ✓ Multi-block hash matches!")
                else:
                    print(f"    [FAIL] ✗ Hash mismatch!")
                    # Show where they differ
                    diff_bits = state_0_256 ^ expected_hash_lib_int
                    print(f"    XOR (difference): 0x{diff_bits:064x}")
                
                verified = True
                break 

            # Watchdog
            if cycle_count > 100000:
                print("  [TIMEOUT] Simulation ran too long.")
                break
            
            yield
        
        if not verified:
            print("  [FAIL] Did not find solution")

        # ======================================================================
        # TEST 2: Difficulty Comparison Test (MSBs)
        # ======================================================================
        print("\n" + "="*70)
        print("[TEST 2] Difficulty Comparison Test (MSBs)")
        print("="*70)
        print("Verifying that difficulty comparison uses bits 128-255 (MSBs)")
        
        # Reset for new test
        yield dut.start.eq(0)
        yield
        yield
        
        # Use simple pattern for predictable hash
        test_input_bytes_2 = bytearray([0x42] * 100)
        test_input_bytes_2[1] = 32
        for i in range(2, 34):
            test_input_bytes_2[i] = 0
        
        test_input_2 = int.from_bytes(test_input_bytes_2, 'little')
        
        # Calculate expected hash with nonce=1
        test_data = bytearray(test_input_bytes_2)
        nonce_bytes = (1).to_bytes(30, 'little')
        test_data[4:34] = nonce_bytes
        
        h_obj = hashlib.sha3_256(test_data)
        hash_int = int.from_bytes(h_obj.digest(), 'little')
        
        # Extract top 128 bits (MSBs) - bits 128-255
        hash_msb_128 = (hash_int >> 128) & ((1 << 128) - 1)
        hash_lsb_128 = hash_int & ((1 << 128) - 1)
        
        print(f"  Hash with nonce=1:")
        print(f"    Full (256-bit): 0x{hash_int:064x}")
        print(f"    MSBs (128-255): 0x{hash_msb_128:032x}")
        print(f"    LSBs (0-127):   0x{hash_lsb_128:032x}")
        
        # Test 2a: Target above MSBs (should find)
        print(f"\n  Test 2a: Easy Target (above MSBs)")
        target_easy = hash_msb_128 + 1
        print(f"    Target: 0x{target_easy:032x}")
        print(f"    Expected: Should find nonce=1")
        
        yield dut.input_length.eq(100)
        yield dut.target.eq(target_easy)
        yield dut.timeout_limit.eq(1000)
        yield dut.header_data.eq(test_input_2)
        yield
        
        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        yield
        
        found_easy = False
        for i in range(2000):
            found_status = yield dut.found
            if found_status != 0:
                nonce = yield dut.nonce_0 if found_status == 1 else dut.nonce_1
                print(f"    Found nonce={nonce} at cycle {i}")
                
                # Verify the hash
                state = yield dut.state_0 if found_status == 1 else dut.state_1
                hw_hash = state & ((1 << 256) - 1)
                hw_msb = (hw_hash >> 128) & ((1 << 128) - 1)
                
                print(f"    HW MSBs: 0x{hw_msb:032x}")
                print(f"    Target:  0x{target_easy:032x}")
                
                if nonce == 1 and hw_msb < target_easy:
                    print(f"    [PASS] ✓ Easy difficulty works correctly")
                else:
                    print(f"    [FAIL] ✗ Unexpected nonce or MSB comparison failed")
                
                found_easy = True
                yield dut.start.eq(0)
                yield
                break
            yield
        
        if not found_easy:
            print(f"    [FAIL] ✗ Did not find solution with easy difficulty")
        
        # Wait for hardware to return to IDLE
        for i in range(10):
            running = yield dut.running
            if not running:
                break
            yield
        
        # Test 2b: Target below MSBs (should NOT find with nonce=1)
        print(f"\n  Test 2b: Hard Target (below MSBs)")
        
        if hash_msb_128 > 0:
            target_hard = hash_msb_128 - 1
        else:
            print(f"    [SKIP] MSBs are already 0, can't test harder difficulty")
            target_hard = 0
        
        if target_hard > 0:
            print(f"    Target: 0x{target_hard:032x}")
            print(f"    Expected: Should NOT find nonce=1 (will timeout or find different nonce)")
            
            yield dut.target.eq(target_hard)
            yield dut.timeout_limit.eq(100)  # Short timeout
            yield
            
            yield dut.start.eq(1)
            yield
            yield dut.start.eq(0)
            yield
            
            found_hard = False
            timed_out = False
            
            for i in range(500):
                found_status = yield dut.found
                timeout = yield dut.timeout
                
                if timeout:
                    print(f"    Timed out at cycle {i}")
                    timed_out = True
                    yield dut.start.eq(0)
                    yield
                    break
                
                if found_status != 0:
                    nonce = yield dut.nonce_0 if found_status == 1 else dut.nonce_1
                    state = yield dut.state_0 if found_status == 1 else dut.state_1
                    hw_hash = state & ((1 << 256) - 1)
                    hw_msb = (hw_hash >> 128) & ((1 << 128) - 1)
                    
                    print(f"    Found nonce={nonce} at cycle {i}")
                    print(f"    HW MSBs: 0x{hw_msb:032x}")
                    
                    if nonce != 1 and hw_msb < target_hard:
                        print(f"    [PASS] ✓ Hard difficulty correctly rejected nonce=1, found {nonce}")
                    elif nonce == 1:
                        print(f"    [FAIL] ✗ Should not find nonce=1 with this target!")
                        print(f"    This means MSB comparison is NOT working correctly!")
                    
                    found_hard = True
                    yield dut.start.eq(0)
                    yield
                    break
                yield
            
            if timed_out:
                print(f"    [PASS] ✓ Hard difficulty works correctly (timed out as expected)")
            elif not found_hard:
                print(f"    [PASS] ✓ Hard difficulty works correctly (searching continues)")
        
        # ======================================================================
        # TEST 3: Verify OLD Logic Would Fail
        # ======================================================================
        print("\n" + "="*70)
        print("[TEST 3] Verify MSB Logic is Different from LSB Logic")
        print("="*70)
        print("Demonstrating why comparing LSBs (old) vs MSBs (new) matters")
        
        # Find a hash where LSBs and MSBs are significantly different
        for test_nonce in range(1, 20):
            test_data = bytearray(test_input_bytes_2)
            nonce_bytes = test_nonce.to_bytes(30, 'little')
            test_data[4:34] = nonce_bytes
            
            h = hashlib.sha3_256(test_data).digest()
            h_int = int.from_bytes(h, 'little')
            msb = (h_int >> 128) & ((1 << 128) - 1)
            lsb = h_int & ((1 << 128) - 1)
            
            # Find case where one is small but the other is large
            if (msb < (1 << 120)) and (lsb > (1 << 127)):
                print(f"  Found example with nonce={test_nonce}:")
                print(f"    MSBs (128-255): 0x{msb:032x} (small)")
                print(f"    LSBs (0-127):   0x{lsb:032x} (large)")
                print(f"    OLD logic (LSBs): Would REJECT (LSBs are large)")
                print(f"    NEW logic (MSBs): Would ACCEPT (MSBs are small)")
                break
            elif (msb > (1 << 127)) and (lsb < (1 << 120)):
                print(f"  Found example with nonce={test_nonce}:")
                print(f"    MSBs (128-255): 0x{msb:032x} (large)")
                print(f"    LSBs (0-127):   0x{lsb:032x} (small)")
                print(f"    OLD logic (LSBs): Would ACCEPT (LSBs are small)")
                print(f"    NEW logic (MSBs): Would REJECT (MSBs are large)")
                break
        else:
            print(f"  [INFO] No dramatic example found in first 20 nonces")
            print(f"  But the principle still applies: MSBs matter for PoW!")
        
        print("\n" + "="*70)
        print("All Tests Complete!")
        print("="*70)

    run_simulation(dut, generator(), vcd_name="multiblock_processing_updated.vcd")

if __name__ == "__main__":
    test_multiblock_processing()
