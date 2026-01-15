#!/usr/bin/env python3

"""
SHA3 TxPoW Controller CSR Test (Updated for CLZ)

Description:
    This test loads data into the controller using CSR registers and verifies
    the mining functionality. This test accesses the hardware through the
    SHA3TxPoWController wrapper (CSR interface), unlike test_multiblock_processing.py
    which accesses the KeccakDatapath core directly.

Architecture:
    - Uses SHA3TxPoWController (wrapper with CSR registers)
    - Accesses hardware via CSR registers: _nonce_result, _debug_hash0/1, _debug_clz0/1
    - Uses CSR control/status registers: _control, _status, _input_len, _target_clz
    - Writes data via CSR windowed interface: _header_addr, _header_data_low/high, _header_we

Usage:
    python3 test_sha3_txpow_controller_csr.py [input_size] [target_clz]
    
    input_size: Input data size in bytes (default: 100, max: 2176)
    target_clz: Target leading zeros (default: 0 = accept any hash)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from migen import *
from migen.sim import run_simulation
from sha3_txpow_controller import SHA3TxPoWController
from sha3_txpow_controller import WORD_BYTES
import hashlib

from sha3_txpow_controller import (
    MNONCE_DATA_FIELD_OVERWRITE_SPACING,
    MNONCE_DATA_FIELD_OVERWRITE_SIZE, 
    MNONCE_DATA_FIELD_BYTE_SIZE
)


# ==============================================================================
# Helper Functions
# ==============================================================================

def generate_byte_array(length):
    """
    Generate a test byte array with repeating pattern.
    
    Args:
        length: Total length of the byte array
    
    Returns:
        bytearray with the test pattern
    """
    test_bytes = bytearray()
    pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
    for i in range(length):
        test_bytes.append(pattern[i % len(pattern)])
    
    # Set nonce/header locations
    test_bytes[0] = 1
    test_bytes[1] = 32
    for i in range(2, 34):
        test_bytes[i] = 0
    
    return test_bytes

def write_header_via_csr(dut, header_bytes):
    """Writes data one word at a time using the Windowed CSRs."""
    data_to_write = bytearray(header_bytes)
    num_words = (len(data_to_write) + WORD_BYTES - 1) // WORD_BYTES
    
    for word_idx in range(num_words):
        start = word_idx * WORD_BYTES
        end = min(start + WORD_BYTES, len(data_to_write))
        chunk = data_to_write[start:end]
        
        # Pad to 8 bytes with zeros
        while len(chunk) < WORD_BYTES: 
            chunk.append(0)
        
        # Convert to 64-bit word (little-endian)
        word_value = int.from_bytes(chunk, 'little')
        
        # Split into low 32 and high 32 bits for 32-bit CSR bus
        low_32 = word_value & 0xFFFFFFFF
        high_32 = (word_value >> 32) & 0xFFFFFFFF
        
        # Write Sequence
        yield dut._header_addr.storage.eq(word_idx)
        yield
        yield dut._header_data_low.storage.eq(low_32)
        yield
        yield dut._header_data_high.storage.eq(high_32)
        yield
        yield dut._header_we.storage.eq(1) # Strobe Write
        yield
        yield dut._header_we.storage.eq(0)
        yield

def verify_hardware_state(dut, original_test_bytes, target_clz):
    """
    Reads HW state, calculates expected Python hash, and prints a comparison report.
    """
    # 1. Read Nonce
    nonce_full = yield dut._nonce_result.status
    # Extract nonce bytes (32 bytes total: bytes 0-1 are spacing, bytes 2-31 are 30-byte nonce)
    nonce_bytes_full = nonce_full.to_bytes(MNONCE_DATA_FIELD_BYTE_SIZE, 'little')
    
    # Extract 30-byte nonce from bytes 2-31 of the register
    nonce_30_bytes = nonce_bytes_full[2:32]
    
    # 2. Reconstruct Data
    expected_data = bytearray(original_test_bytes)
    # Overwrite bytes 4-33 with the 30-byte nonce (matching hardware behavior)
    expected_data[4:34] = nonce_30_bytes
    
    # 3. Calculate Python Hash
    h = hashlib.sha3_256(expected_data)
    h_digest = h.digest()
    h_int_le = int.from_bytes(h_digest, 'little')
    h_int_be = int.from_bytes(h_digest, 'big')
    
    # 4. Read Hardware State (use debug registers)
    found_src = yield dut.miner.found
    if found_src == 2: 
        hw_hash_le = yield dut._debug_hash1.status
        winning_clz = yield dut._debug_clz1.status
    else: 
        hw_hash_le = yield dut._debug_hash0.status
        winning_clz = yield dut._debug_clz0.status
    
    # 5. Read CLZ values for both cores
    clz_0 = yield dut._debug_clz0.status
    clz_1 = yield dut._debug_clz1.status
    
    # 6. Format for Display
    hw_hash_be = int.from_bytes(hw_hash_le.to_bytes(32, 'little'), 'big')
    nonce_hex_le = ''.join(f'{b:02X}' for b in nonce_30_bytes)
    
    # 7. Print Report
    print(f"\n    Nonce (LE):    0x{nonce_hex_le}")
    print(f"    Expected (BE): 0x{h_int_be:064X}")
    print(f"    Actual   (HW): 0x{hw_hash_be:064X}")
    print(f"    Core 0 CLZ: {clz_0}")
    print(f"    Core 1 CLZ: {clz_1}")
    print(f"    Winner CLZ: {winning_clz}")
    
    # 8. Verify
    hash_match = (h_int_le == hw_hash_le)
    clz_sufficient = (winning_clz >= target_clz)
    
    if hash_match and clz_sufficient:
        print(f"    [PASS] ✓ Hash matches and CLZ >= {target_clz}!")
    elif not hash_match:
        print(f"    [FAIL] ✗ Hash mismatch!")
        diff_bits = hw_hash_be ^ h_int_be
        print(f"    XOR (difference): 0x{diff_bits:064X}")
    elif not clz_sufficient:
        print(f"    [FAIL] ✗ CLZ={winning_clz} < target={target_clz}!")
        
    return hash_match and clz_sufficient

# ==============================================================================
# Main Test
# ==============================================================================

def test_csr_mode(input_size=100, target_clz=0):
    print("="*70)
    print("SHA3 TxPoW Controller CSR Test Suite")
    print("="*70)
    print(f"Input Size:  {input_size} bytes")
    print(f"Target CLZ:  {target_clz} leading zeros")
    
    dut = SHA3TxPoWController()
    
    # Calculate expected blocks
    EXPECTED_BLOCKS = (input_size // 136) + 1
    timeout_cycles = 200000 if target_clz > 0 else 100000

    def generator():
        # ======================================================================
        # Hash Validity Test
        # ======================================================================
        print("\n" + "="*70)
        print(f"[TEST] Hash Validity Test ({input_size} Bytes)")
        print("="*70)
        
        # 1. Setup Input Data
        test_input_bytes = generate_byte_array(input_size)
        
        print(f"  Input Size: {len(test_input_bytes)} bytes")
        print(f"  Expected Blocks: {EXPECTED_BLOCKS}")
        print(f"  Target CLZ: {target_clz}")

        # 2. Write header data via CSR
        yield from write_header_via_csr(dut, test_input_bytes)
        
        # Wait for internal writes to settle
        for _ in range(10): yield
        
        # 3. Configure DUT
        yield dut._input_len.storage.eq(len(test_input_bytes))
        yield dut._target_clz.storage.eq(target_clz)
        yield dut._timeout.storage.eq(timeout_cycles)
        yield
        
        # 4. Wait for Idle
        while True:
            status = yield dut._status.status
            if status & 1: break  # Idle bit
            yield
        
        # 5. Start Miner
        yield dut._control.storage.eq(1)
        yield
        yield dut._control.storage.eq(0)
        yield
        
        # 6. Poll for Completion
        cycle_count = 0
        verified = False
        last_debug_block_data = None
        block_iteration = 0
        debug_read_interval = 25  # Read every ~25 cycles (covers ABSORB + some PERMUTE cycles)
        
        print(f"\n  [DEBUG] Monitoring block data for each iteration...")
        print(f"  Expected blocks: {EXPECTED_BLOCKS}")
        
        while True:
            status = yield dut._status.status
            found = (status >> 2) & 1
            timeout = (status >> 3) & 1
            running = (status >> 1) & 1
            
            cycle_count += 1
            
            # Read debug_block0_data periodically while running to capture each block
            if running and cycle_count % debug_read_interval == 0:
                debug_block_data = yield dut._debug_block0_data.status
                
                # Check if this is a new block (data changed)
                if debug_block_data != last_debug_block_data:
                    block_iteration += 1
                    last_debug_block_data = debug_block_data
                    
                    # Convert to bytes for display
                    block_bytes = debug_block_data.to_bytes(64, 'little')
                    
                    # Determine if this is Block 0 (has nonce) or subsequent block
                    # Block 0 will have non-zero bytes in the nonce area (bytes 4-33)
                    # Note: This is a heuristic - Block 0 has nonce injected, others don't
                    is_block_0 = (block_iteration == 1) or any(block_bytes[4:34])
                    block_num = block_iteration - 1
                    
                    print(f"\n  [Block {block_num} @ Cycle {cycle_count}] First 64 bytes:")
                    print(f"    Bytes 0-15:   {' '.join(f'{b:02X}' for b in block_bytes[0:16])}")
                    print(f"    Bytes 16-31:  {' '.join(f'{b:02X}' for b in block_bytes[16:32])}")
                    print(f"    Bytes 32-47:  {' '.join(f'{b:02X}' for b in block_bytes[32:48])}")
                    print(f"    Bytes 48-63:  {' '.join(f'{b:02X}' for b in block_bytes[48:64])}")
                    
                    if block_num == 0:
                        print(f"    [Block 0] Nonce area (bytes 4-33) contains nonce data")
                        print(f"    Nonce bytes (4-33): {' '.join(f'{b:02X}' for b in block_bytes[4:34])}")
                    else:
                        print(f"    [Block {block_num}] Raw block data (no nonce injection)")
                    
                    # Stop reading after all expected blocks
                    if block_iteration >= EXPECTED_BLOCKS:
                        debug_read_interval = 10000  # Reduce frequency after initial blocks
            
            if timeout:
                print(f"\n  [TIMEOUT] Simulation ran too long ({cycle_count} cycles).")
                print(f"  Note: Target CLZ={target_clz} may be too high for quick simulation.")
                yield dut._control.storage.eq(0)
                yield; yield
                break
            
            elif found:
                print(f"\n  [Cycle {cycle_count}] Hash 'Found'. Verifying...")
                yield  # Stabilization
                
                # Read final block data before verification
                final_debug_block_data = yield dut._debug_block0_data.status
                if final_debug_block_data != last_debug_block_data:
                    block_bytes = final_debug_block_data.to_bytes(64, 'little')
                    print(f"\n  [Final Block Data @ Cycle {cycle_count}] First 64 bytes:")
                    print(f"    Bytes 0-15:   {' '.join(f'{b:02X}' for b in block_bytes[0:16])}")
                    print(f"    Bytes 16-31:  {' '.join(f'{b:02X}' for b in block_bytes[16:32])}")
                
                # Run Verification Helper
                verified = yield from verify_hardware_state(dut, test_input_bytes, target_clz)
                
                yield dut._control.storage.eq(0)
                yield; yield
                break
            
            # Check if still running or found
            if not running and not found:
                break
            
            # Progress indicator for long runs
            if target_clz > 4 and cycle_count % 10000 == 0:
                print(f"    Cycle {cycle_count}...", end='\r')
            
            yield
        
        if not verified and not timeout:
            print("  [FAIL] Did not find solution")
        
        print("\n" + "="*70)
        print("Test Complete!")
        print("="*70)

    run_simulation(dut, generator(), vcd_name="sha3_txpow_csr_corrected.vcd")

if __name__ == "__main__":
    # Parse command line arguments
    input_size = 100  # Default
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
    
    print(f"SHA3 TxPoW Controller CSR Testbench")
    print(f"Usage: python3 test_sha3_txpow_controller_csr.py [input_size] [target_clz]")
    print(f"  input_size: 1-2176 bytes (default: 100)")
    print(f"  target_clz: 0-256 leading zeros (default: 0)")
    print()
    
    test_csr_mode(input_size, target_clz)
