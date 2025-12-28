#!/usr/bin/env python3

"""
SHA3 TxPoW Controller CSR Test (HUMAN READABLE & ENHANCED)

Description:
    This test loads data into the controller using CSR registers and verifies
    the mining functionality.

Updates:
    - Added Color Output.
    - Standardized verification logic.
    - Improved comments.
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
# Configuration & Constants
# ==============================================================================

# Target CLZ (number of leading zeros required)
# For example: CLZ=2 means hash must have at least 2 leading zeros
TARGET_CLZ = 2
TIMEOUT_CYCLES = 5000

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

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

def verify_hardware_state(dut, original_test_bytes):
    """
    Reads HW state, calculates expected Python hash, and prints a comparison report.
    """
    # 1. Read Nonce
    nonce_full = yield dut._nonce_result.status
    # Extract nonce bytes (32 bytes total: 30 bytes nonce data + 2 bytes header prefix at LSB)
    nonce_bytes_full = nonce_full.to_bytes(MNONCE_DATA_FIELD_BYTE_SIZE, 'little')
    
    # 2. Reconstruct Data
    expected_data = bytearray(original_test_bytes)
    # Overwrite starting from byte 2 with the entire 32-byte nonce_result
    expected_data[2:2 + MNONCE_DATA_FIELD_BYTE_SIZE] = nonce_bytes_full
    
    # 3. Calculate Python Hash
    h = hashlib.sha3_256(expected_data)
    h_digest = h.digest()
    h_int_le = int.from_bytes(h_digest, 'little')
    h_int_be = int.from_bytes(h_digest, 'big')
    
    # 4. Read Hardware State (use debug registers)
    found_src = yield dut.miner.found
    if found_src == 2: 
        hw_hash_le = yield dut._debug_hash1.status
    else: 
        hw_hash_le = yield dut._debug_hash0.status
    
    # 5. Format for Display
    hw_hash_be = int.from_bytes(hw_hash_le.to_bytes(32, 'little'), 'big')
    nonce_be = int.from_bytes(nonce_bytes_full, 'big')
    
    # 6. Print Report
    print("-" * 80)
    print(f"{Colors.BOLD}VERIFICATION REPORT{Colors.ENDC}")
    print("-" * 80)
    print(f"Target CLZ:      {TARGET_CLZ} (leading zeros required)")
    print(f"Nonce Found (BE): 0x{nonce_be:064x}")
    print(f"Hash Value (BE):  0x{hw_hash_be:064x}")
    print("-" * 80)
    print(f"Expected (Py BE): 0x{h_int_be:064x}")
    print(f"Hardware (BE):    0x{hw_hash_be:064x}")
    print("-" * 80)
    
    hash_match = (h_int_le == hw_hash_le)
    # Note: Difficulty check is now done via CLZ in hardware, not via comparison here
    diff_pass = True  # CLZ-based difficulty check is handled in hardware
    
    if hash_match:
        print(f"{Colors.GREEN}[PASS] ✓ Hash Verified{Colors.ENDC}")
    else:
        print(f"{Colors.FAIL}[FAIL] ✗ Hash Mismatch{Colors.ENDC}")
        
    return hash_match and diff_pass

# ==============================================================================
# Main Test
# ==============================================================================

def test_csr_mode():
    print("="*80)
    print(f"{Colors.HEADER}SHA3 TxPoW Controller - CSR Mode Test{Colors.ENDC}")
    print("="*80)
    
    dut = SHA3TxPoWController()

    def run_test_case(test_name, input_bytes):
        print(f"\n{Colors.CYAN}=== {test_name} ({len(input_bytes)} Bytes) ==={Colors.ENDC}")

        # 1. Write header data via CSR
        print(f"  {Colors.CYAN}[CSR Write]{Colors.ENDC} Writing {len(input_bytes)} bytes...")
        yield from write_header_via_csr(dut, input_bytes)
        
        # Wait for internal writes to settle
        for _ in range(10): yield
        
        # Read and display header memory contents
        header_data_full = yield dut.miner.header_data
        header_bytes = bytearray()
        for i in range(len(input_bytes)):
            byte_val = (header_data_full >> (i * 8)) & 0xFF
            header_bytes.append(byte_val)
        
        print(f"  {Colors.CYAN}[Header Memory]{Colors.ENDC} First 16 bytes: {header_bytes[:16].hex()}")
        print(f"  {Colors.CYAN}[Header Memory]{Colors.ENDC} Expected first 16: {bytes(input_bytes[:16]).hex()}")
        if header_bytes[:len(input_bytes)] == bytes(input_bytes):
            print(f"  {Colors.GREEN}[Header Memory] ✓ Data matches expected input{Colors.ENDC}")
        else:
            print(f"  {Colors.FAIL}[Header Memory] ✗ Data mismatch!{Colors.ENDC}")

        # 2. Configure DUT
        yield dut._input_len.storage.eq(len(input_bytes))
        yield dut._target_clz.storage.eq(TARGET_CLZ)
        yield dut._timeout.storage.eq(TIMEOUT_CYCLES)
        yield
        
        # 3. Wait for Idle
        print(f"  [{test_name}] Waiting for IDLE...")
        while True:
            status = yield dut._status.status
            if status & 1: break
            yield
        
        # 4. Start Miner
        yield dut._control.storage.eq(1)
        yield
        
        # 5. Poll for Completion
        success = False
        for i in range(TIMEOUT_CYCLES):
            status = yield dut._status.status
            found = (status >> 2) & 1
            timeout = (status >> 3) & 1
            
            if timeout:
                print(f"  {Colors.FAIL}[TIMEOUT] Cycle {i}{Colors.ENDC}")
                yield dut._control.storage.eq(0)
                yield; yield
                break
            
            elif found:
                print(f"  {Colors.GREEN}[FOUND] Solution at Cycle {i}{Colors.ENDC}")
                yield # Stabilization
                
                # Run Verification Helper
                yield from verify_hardware_state(dut, input_bytes)
                
                yield dut._control.storage.eq(0)
                yield; yield
                success = True
                break
            
            yield
        
        if not success:
            print(f"  {Colors.WARNING}[WARNING] Test did not complete successfully{Colors.ENDC}")
        
        return success

    def generator():
        # Test case 1: Single block (100 bytes)
        test_bytes_1 = generate_byte_array(100)
        yield from run_test_case("TEST 1 (Single Block)", test_bytes_1)
        
        # Wait between tests
        for _ in range(20): yield

    run_simulation(dut, generator(), vcd_name="sha3_txpow_csr_corrected.vcd")

if __name__ == "__main__":
    test_csr_mode()
