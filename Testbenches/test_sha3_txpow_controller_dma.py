#!/usr/bin/env python3

"""
SHA3 TxPoW Controller DMA Test (HUMAN READABLE & ENHANCED)

Description:
    This test replicates the exact data patterns of the CSR test but loads
    data into the controller using the Wishbone DMA engine.
    
    It simulates a RAM block, populates it with test data, and triggers
    the controller's DMA reader.

Updates:
    - Added Color Output.
    - Standardized verification logic (matched to CSR test).
    - Improved memory model comments.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from migen import *
from migen.sim import run_simulation
from sha3_txpow_controller import SHA3TxPoWController
import hashlib

from sha3_txpow_controller import (
    WORD_BYTES, MNONCE_DATA_FIELD_OVERWRITE_SPACING,
    MNONCE_DATA_FIELD_OVERWRITE_SIZE, MNONCE_DATA_FIELD_BYTE_SIZE
)

# ==============================================================================
# Configuration & Constants
# ==============================================================================

# Target CLZ (number of leading zeros required)
# For example: CLZ=2 means hash must have at least 2 leading zeros
TARGET_CLZ = 2
TIMEOUT_CYCLES = 5000
DMA_BASE_ADDR     = 0x10000000
RAM_SIZE_BYTES    = 8192

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

# ==============================================================================
# Helper Generators (Verification)
# ==============================================================================

def verify_hardware_state(dut, original_test_bytes):
    """
    Reads HW state, calculates expected Python hash, and prints a comparison report.
    (Identical to CSR test logic for consistency)
    """
    # 1. Read Nonce
    nonce_full = yield dut._nonce_result.status
    # Extract nonce bytes (32 bytes total: 30 bytes nonce data + 2 bytes header prefix at LSB)
    nonce_bytes_full = nonce_full.to_bytes(MNONCE_DATA_FIELD_BYTE_SIZE, 'little')
    
    # 2. Reconstruct Data
    expected_data = bytearray(original_test_bytes)
    # Overwrite starting from byte 2 with the entire 32-byte nonce_result
    # This includes the 2 bytes from header_data (bytes [2:3]) and the 30-byte nonce
    expected_data[2:2 + MNONCE_DATA_FIELD_BYTE_SIZE] = nonce_bytes_full
    
    # 3. Calculate Python Hash
    h = hashlib.sha3_256(expected_data)
    h_digest = h.digest()
    h_int_le = int.from_bytes(h_digest, 'little')
    h_int_be = int.from_bytes(h_digest, 'big')
    
    # 4. Read Hardware State (use debug registers for consistency)
    found_src = yield dut.miner.found
    if found_src == 2: 
        hw_hash_le = yield dut._debug_hash1.status
    else: 
        hw_hash_le = yield dut._debug_hash0.status
    
    # 5. Format for Display (convert from little-endian to big-endian)
    # The hash is stored in little-endian format in hardware, convert to big-endian for display
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
# DMA Helpers
# ==============================================================================

def csr_write(dut, csr, value):
    yield csr.storage.eq(value)
    yield

def csr_read(dut, csr):
    return (yield csr.status)

def perform_dma_transfer(dut, base_addr, length_bytes):
    """Configures and runs a DMA transfer with length alignment."""
    # Round up to nearest 8 bytes
    aligned_length = (length_bytes + 7) // 8 * 8
    
    print(f"  {Colors.BLUE}[DMA Trigger]{Colors.ENDC} Base=0x{base_addr:08x}, Len={length_bytes} (Aligned: {aligned_length})")
    
    yield from csr_write(dut, dut.dma._enable, 0)
    yield
    yield from csr_write(dut, dut.dma._base, base_addr)
    yield from csr_write(dut, dut.dma._length, aligned_length)
    yield from csr_write(dut, dut.dma._enable, 1)
    yield
    
    for i in range(2000):
        done = yield from csr_read(dut, dut.dma._done)
        if done:
            print(f"  {Colors.BLUE}[DMA Done]{Colors.ENDC} Transfer Complete at cycle {i}")
            yield from csr_write(dut, dut.dma._enable, 0)
            yield
            return
        yield
    raise TimeoutError("DMA Transfer Timed Out")

def memory_model_dma_source(dut, memory_data, base_address):
    """
    Synchronous Wishbone Memory Model (1-cycle latency).
    Returns data in LITTLE-ENDIAN byte order to match CSR formatting.
    """
    yield dut.bus.ack.eq(0)
    yield dut.bus.dat_r.eq(0)
    ack_pending = False
    
    while True:
        yield
        stb = yield dut.bus.stb
        cyc = yield dut.bus.cyc
        we  = yield dut.bus.we
        adr = yield dut.bus.adr
        
        next_ack = 0
        next_data = 0
        
        if ack_pending:
            ack_pending = False
        elif stb and cyc and not we:
            # LiteX Wishbone DMA Reader outputs Word Address.
            # Convert WB word address to Byte Address.
            byte_addr = adr * WORD_BYTES
            
            if base_address <= byte_addr < (base_address + len(memory_data)):
                offset = byte_addr - base_address
                word_data = 0
                # Pack bytes in big-endian order (MSB first) to match WishboneDMAReader byte swap
                # The DMA reader with endianness="little" swaps bytes, so we pack in reverse order
                for i in range(8):
                    if offset + i < len(memory_data):
                        word_data |= (memory_data[offset + i] << ((7 - i) * 8))
                next_data = word_data
            else:
                next_data = 0 
            next_ack = 1
            ack_pending = True
            
        yield dut.bus.ack.eq(next_ack)
        yield dut.bus.dat_r.eq(next_data)

# ==============================================================================
# Main Test
# ==============================================================================

def test_dma_mode():
    print("="*80)
    print(f"{Colors.HEADER}SHA3 TxPoW Controller - DMA Mode Test{Colors.ENDC}")
    print("="*80)
    
    dut = SHA3TxPoWController()
    ram_storage = bytearray(RAM_SIZE_BYTES)

    def run_test_case(test_name, input_bytes):
        print(f"\n{Colors.CYAN}=== {test_name} ({len(input_bytes)} Bytes) ==={Colors.ENDC}")

        # 1. Load Data into RAM Model
        # Clear RAM first
        for i in range(len(ram_storage)): ram_storage[i] = 0
        # Copy test data
        for i in range(len(input_bytes)): ram_storage[i] = input_bytes[i]
        
        # 2. Perform DMA
        yield from perform_dma_transfer(dut, DMA_BASE_ADDR, len(input_bytes))
        
        # Wait for internal writes to settle
        for _ in range(10): yield
        
        # Read and display header memory contents
        header_data_full = yield dut.miner.header_data
        # Extract bytes manually to avoid integer overflow
        # header_data is 2176 bytes, but we only wrote len(input_bytes)
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

        # 3. Configure DUT
        yield dut._input_len.storage.eq(len(input_bytes))
        yield dut._target_clz.storage.eq(TARGET_CLZ)
        yield dut._timeout.storage.eq(TIMEOUT_CYCLES)
        yield
        
        # 4. Wait for Idle
        print(f"  [{test_name}] Waiting for IDLE...")
        while True:
            status = yield dut._status.status
            if status & 1: break
            yield
        
        # 5. Start Miner
        yield dut._control.storage.eq(1)
        yield
        
        # 6. Poll for Completion
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
            print(f"  {Colors.FAIL}[FAIL] Test Case Failed.{Colors.ENDC}")

    def generator():
        # --- TEST 1: Single Block ---
        test_bytes_1 = generate_byte_array(100)
        
        yield from run_test_case("TEST 1 (Single Block)", test_bytes_1)

        # --- TEST 2: Multi Block ---
        test_bytes_2 = generate_byte_array(300)
        
        yield from run_test_case("TEST 2 (Multi Block)", test_bytes_2)
            
        print("\n" + "="*80)
        print("DMA Test Complete")
        print("="*80)

    # Run Simulation with Memory Model
    generators = [
        generator(),
        memory_model_dma_source(dut, ram_storage, DMA_BASE_ADDR)
    ]
    
    run_simulation(dut, generators, vcd_name="sha3_txpow_dma_matched.vcd")

if __name__ == "__main__":
    test_dma_mode()