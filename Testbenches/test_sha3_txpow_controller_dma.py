#!/usr/bin/env python3

"""
SHA3 TxPoW Controller DMA Test - Final Verified
1. DMA Integrity: Verifies 2048-byte transfer.
2. Hash Test 1: DMA loads 100 bytes (Aligned), Controller mines.
3. Hash Test 2: DMA loads 300 bytes (Aligned), Controller mines & Verifies Hash.

Fixes:
- ALIGNMENT: Rounds DMA length up to nearest 8 bytes (300 -> 304).
- TIMING: Added yields to prevent reading stale nonce values.
"""

from migen import *
from migen.sim import run_simulation
import sys
import os
import hashlib

# Add parent directory to path to find local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sha3_txpow_controller import (
    SHA3TxPoWController, 
    WORD_BYTES,
    MNONCE_DATA_FIELD_OVERWRITE_LOCATION,
    MNONCE_DATA_FIELD_OVERWRITE_SIZE
)

# Constants
HEADER_SIZE_BYTES = 2048
HEADER_WORDS = HEADER_SIZE_BYTES // WORD_BYTES

# ==============================================================================
# Helper Functions
# ==============================================================================

def csr_write(dut, csr, value):
    yield csr.storage.eq(value)
    yield

def csr_read(dut, csr):
    return (yield csr.status)

def memory_model_dma_source(dut, memory_data, base_address):
    """Synchronous Wishbone Memory Model (1-cycle latency)."""
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
            byte_addr = adr * WORD_BYTES
            if base_address <= byte_addr < (base_address + len(memory_data)):
                offset = byte_addr - base_address
                word_data = 0
                for i in range(8):
                    if offset + i < len(memory_data):
                        word_data |= (memory_data[offset + i] << (i * 8))
                next_data = word_data
            else:
                next_data = 0
            next_ack = 1
            ack_pending = True
            
        yield dut.bus.ack.eq(next_ack)
        yield dut.bus.dat_r.eq(next_data)

# ==============================================================================
# DMA Helper (With Alignment Fix)
# ==============================================================================

def perform_dma_transfer(dut, base_addr, length_bytes):
    """Configures and runs a DMA transfer with length alignment."""
    # ALIGNMENT FIX: Round up to nearest 8 bytes so DMA sends the tail.
    # 300 bytes -> 304 bytes (38 words).
    aligned_length = (length_bytes + 7) // 8 * 8
    
    print(f"  [DMA] Starting Transfer: Req={length_bytes}, Aligned={aligned_length} bytes")
    
    yield from csr_write(dut, dut.dma._enable, 0)
    yield
    yield from csr_write(dut, dut.dma._base, base_addr)
    yield from csr_write(dut, dut.dma._length, aligned_length)
    yield from csr_write(dut, dut.dma._enable, 1)
    yield
    
    for i in range(2000):
        done = yield from csr_read(dut, dut.dma._done)
        if done:
            print(f"  [DMA] Transfer Complete at cycle {i}")
            yield from csr_write(dut, dut.dma._enable, 0)
            yield
            return
        yield
    raise TimeoutError("DMA Transfer Timed Out")

# ==============================================================================
# Test Sequences
# ==============================================================================

def test_sequence(dut, ram_storage, dma_base_addr):
    # --- PHASE 1: Verify DMA Integrity (2048 Bytes) ---
    print(f"\n{'='*60}")
    print("[PHASE 1] Verifying DMA Integrity (2048 Bytes)")
    print(f"{'='*60}")
    
    test_pattern = bytearray(HEADER_SIZE_BYTES)
    for i in range(HEADER_SIZE_BYTES):
        test_pattern[i] = (i + 0x10) & 0xFF
        ram_storage[i] = test_pattern[i] 

    yield from perform_dma_transfer(dut, dma_base_addr, HEADER_SIZE_BYTES)

    errors = 0
    for i in range(HEADER_WORDS):
        actual = yield dut.miner.header_data[i*64:(i+1)*64]
        expected = 0
        for b in range(8):
            expected |= (test_pattern[i*8 + b] << (b*8))
        if actual != expected:
            if errors < 5: print(f"    Error Word {i}: Got 0x{actual:016x}, Exp 0x{expected:016x}")
            errors += 1
    
    if errors == 0:
        print("  [PASS] DMA Integrity Verified.")
    else:
        print(f"  [FAIL] {errors} mismatches.")
        return

    # --- PHASE 2: Single Block Hash (100 Bytes) ---
    print(f"\n{'='*60}")
    print("[PHASE 2] Single Block Hash (100 Bytes)")
    print(f"{'='*60}")
    
    input_bytes = bytearray()
    pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
    for i in range(100):
        input_bytes.append(pattern[i % len(pattern)])
    
    input_bytes[1] = 32
    for i in range(2, 34): input_bytes[i] = 0
    
    for i in range(len(input_bytes)):
        ram_storage[i] = input_bytes[i]
        
    yield from perform_dma_transfer(dut, dma_base_addr, len(input_bytes))
    
    yield dut._input_len.storage.eq(len(input_bytes))
    yield dut._target.storage.eq(0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF)
    yield dut._timeout.storage.eq(5000)
    yield
    
    yield dut._control.storage.eq(1)
    yield
    yield dut._control.storage.eq(0)
    yield
    
    found = False
    for i in range(5000):
        status = yield dut._status.status
        if (status >> 1) & 1:
            print(f"  [MINER] Solution Found at cycle {i}!")
            yield # FIX: Wait one cycle for latch
            found = True
            break
        yield
    if not found: print("  [FAIL] Timeout waiting for solution.")
    else: print("  [PASS] Single Block Test Passed.")

    # --- PHASE 3: Multi-Block Hash (300 Bytes) ---
    print(f"\n{'='*60}")
    print("[PHASE 3] Multi-Block Hash (300 Bytes)")
    print(f"{'='*60}")

    # Generate 300 bytes of data
    input_bytes_2 = bytearray()
    for i in range(300):
        input_bytes_2.append(pattern[i % len(pattern)])
    input_bytes_2[1] = 32
    for i in range(2, 34): input_bytes_2[i] = 0
    
    # Update RAM
    for i in range(len(input_bytes_2)):
        ram_storage[i] = input_bytes_2[i]
        
    # Transfer 304 bytes (Aligned)
    yield from perform_dma_transfer(dut, dma_base_addr, len(input_bytes_2))
    
    yield dut._input_len.storage.eq(len(input_bytes_2))
    yield
    
    yield dut._control.storage.eq(1)
    yield
    yield dut._control.storage.eq(0)
    yield
    
    found = False
    for i in range(5000):
        status = yield dut._status.status
        if (status >> 1) & 1:
            print(f"  [MINER] Solution Found at cycle {i}!")
            
            # FIX: Wait 1 cycle for NextValue to latch the new nonce
            yield 
            
            # Read Nonce
            nonce = yield dut._nonce_result.status
            
            # Construct Expected Input for Hash Calculation
            # Use the SAME approach as CSR test - use the original input_bytes_2 directly
            expected_data = bytearray(input_bytes_2)
            
            # Inject Nonce (same as CSR test)
            nonce_bytes = nonce.to_bytes(MNONCE_DATA_FIELD_OVERWRITE_SIZE, 'little')
            loc = MNONCE_DATA_FIELD_OVERWRITE_LOCATION
            size = MNONCE_DATA_FIELD_OVERWRITE_SIZE
            expected_data[loc : loc+size] = nonce_bytes
            
            # Perform Python Hash (same as CSR test)
            h_obj = hashlib.sha3_256(expected_data)
            h_int = int.from_bytes(h_obj.digest(), 'little')
            
            # Read Hardware Hash
            found_src = yield dut.miner.found
            if found_src == 2: state_full = yield dut.miner.state_1
            else: state_full = yield dut.miner.state_0
            hw_hash = state_full & ((1 << 256) - 1)
            
            print(f"  Nonce:    0x{nonce:016x}")
            print(f"  Expected: 0x{h_int:064x} (Python hashlib)")
            print(f"  Actual:   0x{hw_hash:064x} (Hardware)")
            
            if h_int == hw_hash:
                print("  [PASS] \033[92mMulti-Block Test Verified!\033[0m")
            else:
                print("  [FAIL] \033[91mHash Mismatch!\033[0m")
                
            found = True
            break
        yield
        
    if not found:
        print("  [FAIL] Timeout on Multi-Block Test.")

def run_tests():
    print(f"{'='*60}")
    print("SHA3 TxPoW Controller - DMA Functional Verification")
    print(f"{'='*60}")
    
    dut = SHA3TxPoWController()
    RAM_SIZE = 8192
    DMA_BASE = 0x10000000
    ram_storage = bytearray(RAM_SIZE)
    
    generators = [
        test_sequence(dut, ram_storage, DMA_BASE),
        memory_model_dma_source(dut, ram_storage, DMA_BASE)
    ]
    
    run_simulation(dut, generators, vcd_name="sha3_txpow_dma_full.vcd")

if __name__ == "__main__":
    run_tests()