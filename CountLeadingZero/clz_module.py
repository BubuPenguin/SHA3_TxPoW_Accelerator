#!/usr/bin/env python3

"""
Count Leading Zeros (CLZ) Module - Big Endian Compatible
Single Module Implementation

This module implements a "Leading Zero" counter that mimics Java's BigInteger behavior
on Little Endian hardware in a single, unified class.

THE LOGIC EXPLAINED:
--------------------
1. Java (Big Endian) Perspective:
   - "Leading" means starting from Byte 0, Bit 7 (MSB).
   - A byte like 0x01 (binary 0000 0001) is considered "Small" and has 7 leading zeros.

2. Hardware (Little Endian) Perspective:
   - Standard hardware counters look at Bit 0 (LSB) first.
   - Input 0x01 (binary ...00000001): LSB is 1. Standard hardware sees 0 zeros.

3. The Unified Solution:
   - Phase 1 (Swizzle): We reverse the bits *within each byte*. 
     This maps Java's MSB (Bit 7) to the Hardware's LSB (Bit 0).
   - Phase 2 (Search): We run a standard Binary Search / Priority Encoder on this 
     swapped data.

FIX LOG:
- Changed priority encoder loop to iterate from Large Blocks to Small Blocks (Top-Down).
  (e.g., Check lower 128, then lower 64, etc.)
"""

import operator
from functools import reduce
from migen import *
from litex.gen import *

class CountLeadingZeros(Module):
    """
    Big-Endian Compatible Leading Zero Counter.
    
    Combines byte-wise bit reversal and a priority encoder tree to count 
    leading zeros as defined by Java BigInteger on a Little Endian system.
    """
    def __init__(self, width=256):
        self.width = width
        self.i = Signal(width)
        
        # Output width: 9 bits for 256 input (values 0..256)
        output_width = (width).bit_length()
        self.o = Signal(output_width)
        
        # ====================================================================
        # PART 1: Byte-wise Bit Reversal (Swizzling)
        # ====================================================================
        # We create a virtual signal 'reversed_input' that rewires the bus.
        # This aligns Java's MSB with the hardware's LSB for the search tree.
        
        reversed_input = Signal(width, name="bit_reversed_view")
        
        for byte_idx in range(width // 8):
            base = byte_idx * 8
            for bit_idx in range(8):
                # Target: Hardware Bit 0 (LSB) should see Java Bit 7 (MSB)
                # Target: Hardware Bit 1 should see Java Bit 6
                src_bit = base + (7 - bit_idx) # The bit we want to check first (MSB)
                dst_bit = base + bit_idx       # The bit the search tree checks first (LSB)
                
                self.comb += reversed_input[dst_bit].eq(self.i[src_bit])

        # ====================================================================
        # PART 2: Binary Search / Priority Encoder Tree
        # ====================================================================
        # This is a standard "Count Trailing Zeros" logic applied to the REVERSED input.
        # It recursively checks lower halves of the signal.
        
        current_data = reversed_input
        current_offset = Signal(output_width, reset=0)
        
        # FIX: Loop must go from Largest Block (128) down to Smallest Block (1)
        num_stages = (width - 1).bit_length() # 8 stages for 256 bits
        
        for i in reversed(range(num_stages)):
            block_size = 1 << i  # 128, 64, 32, 16, 8, 4, 2, 1
            
            # Create signals for the next stage
            # The width of the data shrinks by half at every stage if we keep the Lower part
            # Or effectively we just take a slice of half the size.
            next_data = Signal(block_size, name=f"clz_data_sz{block_size}")
            next_offset = Signal(output_width, name=f"clz_offset_sz{block_size}")
            
            # Split current view into Low (Priority) and High (Fallback)
            low_part = current_data[:block_size]
            high_part = current_data[block_size:]
            
            # Check if the Low part is entirely zeros
            low_all_zeros = ~reduce(operator.or_, [low_part[j] for j in range(block_size)])
            
            # Mux Logic:
            # If Low is 0s: The first '1' is in High part. 
            #   -> Add 'block_size' to offset.
            #   -> Next stage looks at 'high_part'.
            # If Low has 1s: The first '1' is in Low part.
            #   -> Offset remains same.
            #   -> Next stage looks at 'low_part'.
            self.comb += [
                If(low_all_zeros,
                    next_data.eq(high_part),
                    next_offset.eq(current_offset + block_size)
                ).Else(
                    next_data.eq(low_part),
                    next_offset.eq(current_offset)
                )
            ]
            
            # Advance to next stage
            current_data = next_data
            current_offset = next_offset
        
        # ====================================================================
        # PART 3: Final Output Assignment
        # ====================================================================
        
        self.comb += self.o.eq(current_offset)
        
        # Edge Case: If input is entirely 0, the result is 'width' (e.g., 256)
        all_zeros = ~reduce(operator.or_, [self.i[j] for j in range(width)])
        self.comb += If(all_zeros, self.o.eq(width))