#!/usr/bin/env python3

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from migen import *
from migen.sim import run_simulation
from sha3_txpow_controller import SHA3TxPoWController
import hashlib

from sha3_txpow_controller import (
    WORD_BYTES, MNONCE_DATA_FIELD_OVERWRITE_LOCATION,
    MNONCE_DATA_FIELD_OVERWRITE_SIZE
)

def write_header_via_csr(dut, header_bytes):
    """Writes data one word at a time using the Windowed CSRs."""
    print(f"  [CSR Mode] Writing {len(header_bytes)} bytes manually...")
    
    data_to_write = bytearray(header_bytes)
    num_words = (len(data_to_write) + WORD_BYTES - 1) // WORD_BYTES
    
    for word_idx in range(num_words):
        start = word_idx * WORD_BYTES
        end = min(start + WORD_BYTES, len(data_to_write))
        chunk = data_to_write[start:end]
        while len(chunk) < WORD_BYTES: 
            chunk.append(0)
            
        word_value = int.from_bytes(chunk, 'little')
        
        yield dut._header_addr.storage.eq(word_idx)
        yield dut._header_data.storage.eq(word_value)
        yield dut._header_we.storage.eq(1)
        yield
        yield dut._header_we.storage.eq(0)
        yield

def test_csr_mode():
    print("--- Test: SHA3 TxPoW (CSR Mode - Proven Pattern) ---")
    dut = SHA3TxPoWController()

    def generator():
        # ======================================================
        # TEST 1: Single Block (100 Bytes)
        # ======================================================
        print("\n[TEST 1] Single Block (100 Bytes)")
        
        # Proven Pattern
        test_bytes = bytearray()
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        for i in range(100):
            test_bytes.append(pattern[i % len(pattern)])
        
        test_bytes[1] = 32
        for i in range(2, 34): test_bytes[i] = 0
        
        yield from write_header_via_csr(dut, test_bytes)
        
        yield dut._input_len.storage.eq(len(test_bytes))
        yield dut._target.storage.eq(0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF)
        yield dut._timeout.storage.eq(5000)
        yield
        
        yield dut._control.storage.eq(1)
        yield
        yield dut._control.storage.eq(0)
        yield
        
        found_t1 = False
        for _ in range(5000):
            status = yield dut._status.status
            if (status >> 1) & 1:
                print("  [CSR Mode] Solution Found!")
                yield # Wait 1 cycle for register latch
                found_t1 = True
                break
            yield
        
        if not found_t1: return

        # ======================================================
        # TEST 2: Multi-Block (300 Bytes)
        # ======================================================
        print("\n[TEST 2] Multi-Block (300 Bytes)")
        
        # Proven Pattern (Same as the working testbench)
        test_bytes_2 = bytearray()
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        for i in range(300):
            test_bytes_2.append(pattern[i % len(pattern)])
            
        test_bytes_2[1] = 32
        for i in range(2, 34): test_bytes_2[i] = 0
        
        yield from write_header_via_csr(dut, test_bytes_2)
        
        yield dut._input_len.storage.eq(len(test_bytes_2))
        yield
        
        yield dut._control.storage.eq(1) 
        yield
        yield dut._control.storage.eq(0)
        yield
        
        found_t2 = False
        for i in range(5000):
            status = yield dut._status.status
            if (status >> 1) & 1:
                print(f"  [CSR Mode] Solution Found at cycle {i}!")
                yield # Wait 1 cycle for register latch
                
                nonce = yield dut._nonce_result.status
                
                # Verify
                expected_data = bytearray(test_bytes_2)
                nonce_bytes = nonce.to_bytes(MNONCE_DATA_FIELD_OVERWRITE_SIZE, 'little')
                loc = MNONCE_DATA_FIELD_OVERWRITE_LOCATION
                size = MNONCE_DATA_FIELD_OVERWRITE_SIZE
                expected_data[loc : loc+size] = nonce_bytes
                
                h_obj = hashlib.sha3_256(expected_data)
                h_int = int.from_bytes(h_obj.digest(), 'little')
                
                # Get HW Hash
                found_src = yield dut.miner.found
                if found_src == 2: state_full = yield dut.miner.state_1
                else: state_full = yield dut.miner.state_0
                hw_hash = state_full & ((1 << 256) - 1)
                
                print(f"  Expected: 0x{h_int:064x}")
                print(f"  Actual:   0x{hw_hash:064x}")
                
                if h_int == hw_hash:
                    print("  ✓ TEST 2 PASSED")
                else:
                    print("  ✗ TEST 2 FAILED: Hash mismatch")
                found_t2 = True
                break
            yield
            
        if not found_t2:
            print("  [CSR Mode] FAILED: Timeout on Test 2")

    run_simulation(dut, generator())

if __name__ == "__main__":
    test_csr_mode()