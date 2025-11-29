#!/usr/bin/env python3

"""
Pure DMA Reader Test - Synchronous Fixed
Uses a synchronous state-machine memory model to guarantee 
clean 1-to-1 data transfer without duplication.
"""

from migen import *
from migen.sim import run_simulation
from litex.soc.cores.dma import WishboneDMAReader
from litex.soc.interconnect import wishbone

# Constants
WORD_WIDTH = 64
WORD_BYTES = WORD_WIDTH // 8
TRANSFER_WORDS = 16

class SimpleDMATest(Module):
    def __init__(self):
        # Wishbone bus
        self.bus = wishbone.Interface(data_width=64)
        
        # DMA Reader
        self.submodules.dma = WishboneDMAReader(
            self.bus, 
            endianness="big",
            fifo_depth=16, 
            with_csr=True
        )

# ==============================================================================
# Synchronous Memory Model (The Fix)
# ==============================================================================

def memory_model(dut, memory_data, base_address):
    """
    Synchronous Wishbone Memory Model.
    Behaves like a registered hardware block: 
    Sample Inputs -> Clock Edge -> Update Outputs.
    """
    # Initial State
    yield dut.bus.ack.eq(0)
    yield dut.bus.dat_r.eq(0)
    
    # State variables
    ack_pending = False
    data_pending = 0
    
    while True:
        # 1. Wait for Clock Edge
        # This applies the 'eq's from the previous iteration
        yield
        
        # 2. Sample Bus Inputs (post-clock)
        stb = yield dut.bus.stb
        cyc = yield dut.bus.cyc
        we  = yield dut.bus.we
        adr = yield dut.bus.adr
        
        # 3. Determine Outputs for NEXT cycle
        # Default: clear ACK unless we are responding
        next_ack = 0
        next_data = 0
        
        # If we just ACKed, we must clear it (handshake complete)
        if ack_pending:
            ack_pending = False
            next_ack = 0
            # Don't care about data, bus holds it or clears it
        
        # Otherwise, check for NEW request
        elif stb and cyc and not we:
            # Valid Read Request
            byte_addr = adr * WORD_BYTES
            
            # Construct Data
            if base_address <= byte_addr < (base_address + len(memory_data)):
                offset = byte_addr - base_address
                word_data = 0
                for i in range(8):
                    if offset + i < len(memory_data):
                        word_data |= (memory_data[offset + i] << (i * 8))
                next_data = word_data
            else:
                next_data = 0
            
            # Set ACK for the NEXT cycle
            next_ack = 1
            ack_pending = True
            
        # 4. Schedule Output Updates
        yield dut.bus.ack.eq(next_ack)
        yield dut.bus.dat_r.eq(next_data)

# ==============================================================================
# Pipeline Monitor & Consumer
# ==============================================================================

def pipeline_monitor(dut):
    print(f"\n{'='*90}")
    print("DMA Pipeline Monitor")
    print(f"{'='*90}")
    print(f"{'Cycle':<6} {'Valid':<6} {'Ready':<6} {'Requests':<10} {'Received':<10} {'Data':<18}")
    print(f"{'-'*90}")
    
    words_received_count = 0
    cycle = 0
    
    while words_received_count < TRANSFER_WORDS and cycle < 100:
        valid = yield dut.dma.source.valid
        ready = yield dut.dma.source.ready
        data = yield dut.dma.source.data
        offset = yield dut.dma._offset.status
        
        is_transfer = (valid and ready)
        if is_transfer:
            words_received_count += 1
            
        if cycle < 30 or is_transfer:
            data_str = f"0x{data:016x}" if valid else "-"
            print(f"{cycle:<6} {valid:<6} {ready:<6} {offset:<10} {words_received_count:<10} {data_str:<18}")
            
        yield
        cycle += 1

def data_consumer(dut, expected_words):
    received_data = []
    yield dut.dma.source.ready.eq(1)
    
    while len(received_data) < len(expected_words):
        valid = yield dut.dma.source.valid
        ready = yield dut.dma.source.ready
        data  = yield dut.dma.source.data
        
        if valid and ready:
            received_data.append(data)
        yield

    print(f"\n{'='*90}")
    print("Verification")
    print(f"{'='*90}")
    
    errors = 0
    for i, (actual, expected) in enumerate(zip(received_data, expected_words)):
        match = "✓" if actual == expected else "✗"
        if actual != expected:
            print(f"Word {i}: Received 0x{actual:016x} | Expected 0x{expected:016x} | {match}")
            errors += 1
            
    if errors == 0:
        print(f"\n[PASS] All {len(received_data)} words received correctly.")
    else:
        print(f"\n[FAIL] Found {errors} data errors.")

# ==============================================================================
# Runner
# ==============================================================================

def test_sequence(dut, ram_storage, dma_base):
    # Setup Data
    test_pattern = bytearray(TRANSFER_WORDS * 8)
    expected_words = []
    
    for i in range(len(test_pattern)):
        test_pattern[i] = (i + 0x10) & 0xFF
        ram_storage[i] = test_pattern[i]
        
    for i in range(TRANSFER_WORDS):
        word = 0
        for b in range(8):
            word |= (test_pattern[i*8 + b] << (b*8))
        expected_words.append(word)

    # Config
    yield dut.dma._base.storage.eq(dma_base)
    yield dut.dma._length.storage.eq(len(test_pattern))
    yield
    yield dut.dma._enable.storage.eq(1)
    yield
    
    yield from data_consumer(dut, expected_words)

def run_test():
    dut = SimpleDMATest()
    ram_storage = bytearray(1024)
    
    generators = [
        test_sequence(dut, ram_storage, 0x10000000),
        memory_model(dut, ram_storage, 0x10000000),
        pipeline_monitor(dut)
    ]
    
    run_simulation(dut, generators, vcd_name="pure_dma_sync.vcd")

if __name__ == "__main__":
    run_test()