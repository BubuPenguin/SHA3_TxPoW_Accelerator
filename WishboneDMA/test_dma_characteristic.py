#!/usr/bin/env python3

"""
Minimal test to prove the DMA source.data lag is a LiteX DMA characteristic.
This test will show that when offset=N, source.data contains word N-2.

FIXED: Length is in BYTES, not words!
"""

from migen import *
from migen.sim import run_simulation
from litex.soc.cores.dma import WishboneDMAReader
from litex.soc.interconnect import wishbone

class MinimalDMATest(Module):
    def __init__(self):
        self.bus = wishbone.Interface(data_width=64)
        self.submodules.dma = WishboneDMAReader(
            self.bus, 
            endianness="big",
            fifo_depth=16, 
            with_csr=True
        )

def perfect_memory(dut):
    """
    Perfect memory model - returns word index as data.
    If we read from address N, we return N.
    This makes it trivial to see if the DMA is returning the right data.
    """
    cycle = 0
    while cycle < 50:  # Extended to see more transfers
        stb = yield dut.bus.stb
        cyc = yield dut.bus.cyc
        adr = yield dut.bus.adr
        we  = yield dut.bus.we
        
        # Default: no ack
        yield dut.bus.ack.eq(0)
        
        if stb and cyc and not we:
            # Return the address itself as data (makes checking easy)
            # If reading address 5, return 0x0000000000000005
            yield dut.bus.dat_r.eq(adr)
            yield dut.bus.ack.eq(1)
            print(f"[MEM-{cycle:03d}] Read addr={adr:02d}, returning data={adr:02d}")
        
        yield
        cycle += 1

def dma_verifier(dut):
    """
    Configure DMA and verify the relationship between offset and data.
    Uses the same setup pattern as test_pure_dma.py which works correctly.
    """
    print(f"\n{'='*70}")
    print("DMA Data Lag Verification Test")
    print(f"{'='*70}")
    print("If DMA is correct: when offset=N, data should equal N-1")
    print("If DMA lags:       when offset=N, data will equal N-2 or earlier")
    print(f"{'='*70}\n")
    
    # Set ready FIRST (before enabling DMA)
    yield dut.dma.source.ready.eq(1)
    yield  # Give it a cycle to take effect
    
    # Wait a few cycles for initialization
    for _ in range(3):
        yield
    
    # Configure DMA: read 10 words starting from address 0
    # CRITICAL FIX: base and length are in BYTES, not words!
    # For 64-bit (8-byte) words:
    #   - 10 words = 80 bytes
    #   - The DMA shifts length by log2(data_width/8) = log2(8) = 3
    #   - So internally: 80 >> 3 = 10 word transfers ✓
    yield dut.dma._base.storage.eq(0)
    yield dut.dma._length.storage.eq(10 * 8)  # 80 bytes = 10 words
    yield
    yield  # Extra cycle for CSR to propagate
    
    # Verify configuration was set
    base_check = yield dut.dma._base.storage
    length_check = yield dut.dma._length.storage
    print(f"[CONFIG] Base={base_check} bytes, Length={length_check} bytes ({length_check//8} words)")
    
    # Enable DMA
    yield dut.dma._enable.storage.eq(1)
    yield
    
    # Monitor and verify
    print(f"\n{'Cycle':<6} {'valid':<6} {'ready':<6} {'offset':<7} {'done':<5} {'data':<7} {'Expected':<9} {'Status':<10}")
    print(f"{'-'*90}")
    
    transfers_seen = []
    for cycle_num in range(40):  # Extended to see all 10 transfers
        offset = yield dut.dma._offset.status
        done = yield dut.dma._done.status
        valid = yield dut.dma.source.valid
        ready = yield dut.dma.source.ready
        data = yield dut.dma.source.data
        
        # Always print to see what's happening
        if cycle_num < 25 or valid:  # Print first 25 cycles or when valid
            status = ""
            if valid and ready:
                status = "XFER"
                # When we see a valid transfer, record it
                # Expected: data should be one behind the offset
                # because offset increments AFTER the bus transaction
                # but BEFORE the data appears at source
                expected = offset - 1
                transfers_seen.append((offset, data, expected))
            elif valid:
                status = "WAIT"
            elif done:
                status = "DONE"
            
            if valid:
                expected = offset - 1
                match = "✓" if data == expected else "✗"
                print(f"{cycle_num:<6} {valid:<6} {ready:<6} {offset:<7} {done:<5} {data:<7} {expected:<9} {status:<10} {match}")
            else:
                print(f"{cycle_num:<6} {valid:<6} {ready:<6} {offset:<7} {done:<5} {'-':<7} {'-':<9} {status:<10}")
        
        yield
    
    print(f"\n{'='*70}")
    print(f"Total valid transfers seen: {len(transfers_seen)}")
    print(f"Configured for 10 words, received {len(transfers_seen)}")
    
    if len(transfers_seen) >= 10:
        print("\n✓ SUCCESS: All 10 words transferred!")
        print("\nAnalyzing data lag pattern:")
        print(f"{'offset':<8} {'data':<8} {'expected':<10} {'lag':<6} {'status':<8}")
        print(f"{'-'*50}")
        for offset, data, expected in transfers_seen[:10]:
            lag = expected - data
            match = "✓" if data == expected else "✗"
            print(f"{offset:<8} {data:<8} {expected:<10} {lag:<6} {match:<8}")
            
        # Summary
        all_correct = all(data == expected for _, data, expected in transfers_seen[:10])
        if all_correct:
            print("\n✓ RESULT: DMA data correctly aligned with offset-1")
            print("  This confirms the 1-cycle pipeline delay is inherent to the design.")
        else:
            print("\n✗ RESULT: DMA data shows unexpected lag pattern")
            
    elif len(transfers_seen) == 1:
        print("\n✗ ERROR: DMA stopped after 1 transfer!")
        print("  This was caused by setting length in words instead of bytes.")
    else:
        print(f"\n✗ ERROR: Only received {len(transfers_seen)} transfers")
    
    print(f"{'='*70}")

def run_test():
    dut = MinimalDMATest()
    
    generators = [
        perfect_memory(dut),
        dma_verifier(dut)
    ]
    
    run_simulation(dut, generators, vcd_name="dma_characteristic.vcd")

if __name__ == "__main__":
    run_test()