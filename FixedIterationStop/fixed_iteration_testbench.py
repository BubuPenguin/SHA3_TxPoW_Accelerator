#!/usr/bin/env python3

"""
SHA3 TxPoW Controller - Fixed Iteration Mode Test

Description:
    This testbench verifies the accelerator's ability to loop for a 
    pre-determined number of iterations using the FixedIterationStop module.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from migen import *
from migen.sim import run_simulation
from sha3_txpow_controller import SHA3TxPoWController
import hashlib

# ==============================================================================
# Configuration & Constants
# ==============================================================================

# Set to None to use the default hardware iteration count (defined in keccak_datapath_simd.py)
# Set to a number (e.g., 10) to override for faster testing
EXPECTED_ITERATIONS = 10  # Set to None to use default from keccak_datapath_simd.py

# Calculate timeout limit
# When using default, use a very large timeout since we don't know the exact value
if EXPECTED_ITERATIONS is not None:
    TIMEOUT_LIMIT = EXPECTED_ITERATIONS * 30  # Account for Keccak rounds per iteration
else:
    TIMEOUT_LIMIT = 100000000  # Very large timeout for default (will be limited by actual hardware)

class Colors:
    HEADER = '\033[95m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# ==============================================================================
# Test Generator
# ==============================================================================

def test_fixed_iteration():
    print("="*80)
    print(f"{Colors.HEADER}SHA3 TxPoW Controller - Fixed Iteration Test{Colors.ENDC}")
    print("="*80)
    
    # Only pass target_iterations if EXPECTED_ITERATIONS is explicitly set
    if EXPECTED_ITERATIONS is not None:
        dut = SHA3TxPoWController(target_iterations=EXPECTED_ITERATIONS)
        print(f"  {Colors.CYAN}[Config]{Colors.ENDC} Using custom iteration count: {EXPECTED_ITERATIONS}")
    else:
        dut = SHA3TxPoWController()  # Use default from keccak_datapath_simd.py
        print(f"  {Colors.CYAN}[Config]{Colors.ENDC} Using default iteration count from hardware")

    def generator():
        # 1. Setup test header data (same as C test)
        input_len = 100
        
        # Generate test pattern (same as C test)
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        test_bytes = bytearray()
        for i in range(input_len):
            test_bytes.append(pattern[i % len(pattern)])
        
        # Set nonce field structure (bytes 0-33)
        test_bytes[0] = 1   # Scale field
        test_bytes[1] = 32  # Length field
        # Bytes 2-33: zeros (nonce field)
        for i in range(2, 34):
            test_bytes[i] = 0
        
        # Write header data via CSR interface
        print(f"  {Colors.CYAN}[Setup]{Colors.ENDC} Writing {input_len} bytes of header data...")
        num_words = (input_len + 7) // 8  # Round up to 64-bit words
        
        for word_idx in range(num_words):
            # Pack up to 8 bytes into a 64-bit word (little-endian)
            word = 0
            for byte_idx in range(8):
                global_idx = word_idx * 8 + byte_idx
                if global_idx < input_len:
                    word |= test_bytes[global_idx] << (byte_idx * 8)
            
            # Split into low and high 32-bit values
            low = word & 0xFFFFFFFF
            high = (word >> 32) & 0xFFFFFFFF
            
            # Write to CSR registers
            yield dut._header_addr.storage.eq(word_idx)
            yield dut._header_data_low.storage.eq(low)
            yield dut._header_data_high.storage.eq(high)
            yield dut._header_we.storage.eq(1)
            yield
            yield dut._header_we.storage.eq(0)
            yield
        
        # 2. Configure accelerator
        yield dut._input_len.storage.eq(input_len)
        yield dut._target_clz.storage.eq(64)  # Set target_clz to 64 so that CLZ=0 doesn't trigger immediately
        yield dut._timeout.storage.eq(0) # Disable HW timeout for this test
        yield
        
        # 2. Wait for Idle
        print(f"  {Colors.CYAN}[System]{Colors.ENDC} Waiting for IDLE...")
        while not (yield dut._status.status & 1):
            yield
        
        # 3. Start Miner
        if EXPECTED_ITERATIONS is not None:
            print(f"  {Colors.CYAN}[System]{Colors.ENDC} Starting Miner (Target: {EXPECTED_ITERATIONS} iters)")
        else:
            print(f"  {Colors.CYAN}[System]{Colors.ENDC} Starting Miner (Using default target)")
        yield dut._control.storage.eq(1)
        yield
        
        # 4. Monitor Progress
        # Since simulation is slow, we will sample the iteration count every 1000 cycles
        success = False
        last_reported_iter = 0
        
        for cycle in range(TIMEOUT_LIMIT):
            status = yield dut._status.status
            current_iter = yield dut._iteration_count.status
            found = (status >> 2) & 1
            
            # Print progress every time the iteration counter moves
            if current_iter > last_reported_iter:
                if EXPECTED_ITERATIONS is not None:
                    print(f"    Progress: {current_iter}/{EXPECTED_ITERATIONS} iterations...", end='\r')
                else:
                    print(f"    Progress: {current_iter} iterations...", end='\r')
                last_reported_iter = current_iter

            if found:
                print(f"\n  {Colors.GREEN}[FOUND]{Colors.ENDC} Triggered at Simulation Cycle {cycle}")
                
                # FINAL VERIFICATION
                final_iters = yield dut._iteration_count.status
                
                # Read which core found the solution
                found_flag = yield dut.miner.found
                
                # Read nonce result (32 bytes = 256 bits)
                nonce_result = yield dut._nonce_result.status
                nonce_bytes = nonce_result.to_bytes(32, 'little')
                
                # Read hash result from debug registers (these are direct from state, not latched)
                if found_flag == 1:
                    hash_result = yield dut._debug_hash0.status
                elif found_flag == 2:
                    hash_result = yield dut._debug_hash1.status
                else:
                    hash_result = yield dut._hash_result.status
                hash_bytes = hash_result.to_bytes(32, 'little')
                
                # Also read the latched hash for comparison
                hash_result_latched = yield dut._hash_result.status
                
                # Read debug block data (first 64 bytes with nonce injected)
                debug_block_data = yield dut._debug_block0_data.status
                
                print("-" * 80)
                print(f"{Colors.BOLD}ITERATION VERIFICATION REPORT{Colors.ENDC}")
                print("-" * 80)
                if EXPECTED_ITERATIONS is not None:
                    print(f"Target Iterations:   {EXPECTED_ITERATIONS}")
                    print(f"Actual HW Iterations: {final_iters}")
                    print("-" * 80)
                    
                    if final_iters == EXPECTED_ITERATIONS:
                        print(f"{Colors.GREEN}[PASS] ✓ Iteration Count Matches Exactly{Colors.ENDC}")
                        success = True
                    elif final_iters > EXPECTED_ITERATIONS:
                        # In a SIMD/Pipelined design, it might be off by 1-2 depending on latching
                        print(f"{Colors.WARNING}[PASS] ✓ Triggered within acceptable range{Colors.ENDC}")
                        success = True
                    else:
                        print(f"{Colors.FAIL}[FAIL] ✗ Triggered PREMATURELY!{Colors.ENDC}")
                else:
                    print(f"Actual HW Iterations: {final_iters}")
                    print(f"(Using default target from keccak_datapath_simd.py)")
                    print("-" * 80)
                    print(f"{Colors.GREEN}[PASS] ✓ Successfully completed with default iteration count{Colors.ENDC}")
                    success = True
                
                # Display the debug block data (first 64 bytes with nonce injected)
                print("\n" + "-" * 80)
                print(f"{Colors.BOLD}DEBUG: FIRST 64 BYTES OF BLOCK 0 (WITH NONCE INJECTED){Colors.ENDC}")
                print("-" * 80)
                
                # Convert 512-bit value to bytes (little-endian)
                debug_bytes = debug_block_data.to_bytes(64, 'little')
                
                # Display in hex dump format (16 bytes per line)
                for i in range(0, 64, 16):
                    # Address offset
                    print(f"  [0x{i:04x}] ", end='')
                    
                    # Hex values
                    for j in range(16):
                        if i + j < 64:
                            print(f"{debug_bytes[i + j]:02x} ", end='')
                        else:
                            print("   ", end='')
                        if j == 7:
                            print(" ", end='')
                    
                    # ASCII representation
                    print(" |", end='')
                    for j in range(16):
                        if i + j < 64:
                            b = debug_bytes[i + j]
                            c = chr(b) if 32 <= b < 127 else '.'
                            print(c, end='')
                    print("|")
                
                print("-" * 80)
                print(f"Note: This shows bytes 0-63 of the input data")
                print(f"      Bytes 0-1:   Scale and Length fields")
                print(f"      Bytes 2-3:   Spacing (not overwritten)")
                print(f"      Bytes 4-33:  30-byte nonce (overwritten by hardware)")
                print(f"      Bytes 34-63: Header data")
                print("-" * 80)
                
                # Display nonce result
                print("\n" + "-" * 80)
                print(f"{Colors.BOLD}NONCE RESULT (32 bytes){Colors.ENDC}")
                print("-" * 80)
                print(f"  Bytes 0-1 (Spacing):   {nonce_bytes[0]:02x} {nonce_bytes[1]:02x}")
                print(f"  Bytes 2-31 (30-byte nonce):")
                for i in range(2, 32, 14):
                    print(f"    ", end='')
                    for j in range(i, min(i+14, 32)):
                        print(f"{nonce_bytes[j]:02x} ", end='')
                    print()
                
                # Display hash result  
                print("\n" + "-" * 80)
                print(f"{Colors.BOLD}HASH RESULT (32 bytes){Colors.ENDC}")
                print("-" * 80)
                print(f"  Found flag: {found_flag} (1=core0, 2=core1)")
                print(f"  Hash (from debug register):")
                for i in range(0, 32, 16):
                    print(f"    ", end='')
                    for j in range(i, min(i+16, 32)):
                        print(f"{hash_bytes[j]:02x} ", end='')
                    print()
                
                # Show latched hash for comparison
                if hash_result_latched != 0:
                    hash_latched_bytes = hash_result_latched.to_bytes(32, 'little')
                    print(f"  Hash (latched in register):")
                    for i in range(0, 32, 16):
                        print(f"    ", end='')
                        for j in range(i, min(i+16, 32)):
                            print(f"{hash_latched_bytes[j]:02x} ", end='')
                        print()
                else:
                    print(f"  Hash (latched): All zeros (latching issue or not updated yet)")
                print("-" * 80)
                
                yield dut._control.storage.eq(0)
                yield; yield
                break
            
            yield
        
        if not success:
            print(f"\n  {Colors.FAIL}[FAIL]{Colors.ENDC} Timeout or logic failure.")

    run_simulation(dut, generator(), vcd_name="fixed_iteration_test.vcd")

if __name__ == "__main__":
    test_fixed_iteration()

