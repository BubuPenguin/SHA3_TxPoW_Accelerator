#!/usr/bin/env python3

"""
Multi-Block Processing Test (Updated for CLZ)

Tests:
1. Hash validity for multi-block inputs (configurable size)

Usage:
    python3 test_multiblock_processing.py [input_size] [target_clz]
    
    input_size: Input data size in bytes (default: 300, max: 2176)
    target_clz:  Target leading zeros (default: 0 = accept any hash)
"""

import sys
from pathlib import Path
# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from migen import *
from migen.sim import run_simulation
from keccak_datapath_simd import KeccakDatapath
import hashlib

def test_multiblock_processing(input_size=300, target_clz=0):
    print("="*70)
    print("Multi-Block Processing Test Suite")
    print("="*70)
    print(f"Input Size:  {input_size} bytes")
    print(f"Target CLZ:  {target_clz} leading zeros")
    
    dut = KeccakDatapath(MAX_BLOCKS=16, MAX_DIFFICULTY_BITS=256)

    def generator():
        # ======================================================================
        # Hash Validity Test
        # ======================================================================
        print("\n" + "="*70)
        print(f"[TEST] Hash Validity Test ({input_size} Bytes)")
        print("="*70)
        
        # 1. Setup Input Data
        test_input_bytes = bytearray()
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        for i in range(input_size):
            test_input_bytes.append(pattern[i % len(pattern)])
        
        # Set nonce field structure (matching C test)
        test_input_bytes[0] = 1   # Scale field
        test_input_bytes[1] = 32  # Length field
        for i in range(2, 34):    # Clear Nonce field (bytes 2-33)
            test_input_bytes[i] = 0
        
        # 2. Load as LITTLE ENDIAN
        test_input = int.from_bytes(test_input_bytes, 'little')
        
        EXPECTED_BLOCKS = (len(test_input_bytes) // 136) + 1
        print(f"  Input Size: {len(test_input_bytes)} bytes")
        print(f"  Expected Blocks: {EXPECTED_BLOCKS}")
        print(f"  Target CLZ: {target_clz}")

        yield dut.input_length.eq(input_size)
        yield dut.target_clz.eq(target_clz)
        yield dut.header_data.eq(test_input)

        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        yield

        cycle_count = 0
        verified = False
        max_cycles = 200000 if target_clz > 0 else 100000
        
        while (yield dut.running) or (yield dut.found) != 0:
            cycle_count += 1
            
            # Check if we found a "solution"
            found_status = yield dut.found
            
            if found_status != 0 and not verified:
                winning_core = 0 if found_status == 1 else 1
                state_full = yield dut.state_0 if found_status == 1 else dut.state_1
                
                # Extract SHA3-256 (Bottom 256 bits of state)
                HASH_BITS = 256
                hw_hash_le = state_full & ((1 << HASH_BITS) - 1)
                
                # Convert HW hash from little-endian to big-endian for display
                hw_hash_be = int.from_bytes(hw_hash_le.to_bytes(32, byteorder='little'), byteorder='big')
                
                print(f"\n  [Cycle {cycle_count}] Hash 'Found' (Core {winning_core}). Verifying...")
                
                # Reconstruct expected data
                current_nonce = yield dut.nonce_0 if found_status == 1 else dut.nonce_1
                expected_data = bytearray(test_input_bytes)
                nonce_bytes = current_nonce.to_bytes(30, byteorder='little')
                expected_data[4:34] = nonce_bytes
                
                # Calculate Expected Hash (Library)
                hash_obj = hashlib.sha3_256()
                hash_obj.update(expected_data)
                expected_hash_lib = hash_obj.digest()
                expected_hash_lib_int = int.from_bytes(expected_hash_lib, byteorder='big')
                
                # Get CLZ values
                clz_0 = yield dut.clz_0_out
                clz_1 = yield dut.clz_1_out
                winning_clz = clz_0 if found_status == 1 else clz_1
                
                # Display nonce in little-endian byte order (matches C test and hardware)
                nonce_bytes_le = current_nonce.to_bytes(30, byteorder='little')
                nonce_hex_le = ''.join(f'{b:02X}' for b in nonce_bytes_le)
                
                print(f"    Nonce (LE):    0x{nonce_hex_le}")
                print(f"    Expected (BE): 0x{expected_hash_lib_int:064X}")
                print(f"    Actual   (HW): 0x{hw_hash_be:064X}")
                print(f"    Core 0 CLZ: {clz_0}")
                print(f"    Core 1 CLZ: {clz_1}")
                print(f"    Winner CLZ: {winning_clz}")
                
                # Verify hash matches (compare big-endian representations)
                hash_match = (hw_hash_be == expected_hash_lib_int)
                clz_sufficient = (winning_clz >= target_clz)
                
                if hash_match and clz_sufficient:
                    print(f"    [PASS] ✓ Hash matches and CLZ >= {target_clz}!")
                elif not hash_match:
                    print(f"    [FAIL] ✗ Hash mismatch!")
                    diff_bits = hw_hash_be ^ expected_hash_lib_int
                    print(f"    XOR (difference): 0x{diff_bits:064X}")
                elif not clz_sufficient:
                    print(f"    [FAIL] ✗ CLZ={winning_clz} < target={target_clz}!")
                
                verified = True
                break 

            # Watchdog
            if cycle_count > max_cycles:
                print(f"  [TIMEOUT] Simulation ran too long ({max_cycles} cycles).")
                print(f"  Note: Target CLZ={target_clz} may be too high for quick simulation.")
                break
            
            # Progress indicator for long runs
            if target_clz > 4 and cycle_count % 10000 == 0:
                print(f"    Cycle {cycle_count}...", end='\r')
            
            yield
        
        if not verified:
            print("  [FAIL] Did not find solution")

        print("\n" + "="*70)
        print("Test Complete!")
        print("="*70)

    run_simulation(dut, generator(), vcd_name="multiblock_processing.vcd")

if __name__ == "__main__":
    # Parse command line arguments
    input_size = 300  # Default
    target_clz = 0     # Default (accept any hash)
    
    if len(sys.argv) >= 2:
        try:
            input_size = int(sys.argv[1])
            if input_size < 1 or input_size > 2176:
                print(f"ERROR: input_size must be between 1 and 2176 bytes")
                sys.exit(1)
        except ValueError:
            print(f"ERROR: Invalid input_size format")
            sys.exit(1)
    
    if len(sys.argv) >= 3:
        try:
            target_clz = int(sys.argv[2])
            if target_clz < 0 or target_clz > 256:
                print(f"ERROR: target_clz must be between 0 and 256")
                sys.exit(1)
        except ValueError:
            print(f"ERROR: Invalid target_clz format")
            sys.exit(1)
    
    print(f"SHA3 Multi-Block Processing Testbench")
    print(f"Usage: python3 test_multiblock_processing.py [input_size] [target_clz]")
    print(f"  input_size: 1-2176 bytes (default: 300)")
    print(f"  target_clz: 0-256 leading zeros (default: 0)")
    print()
    
    test_multiblock_processing(input_size, target_clz)
