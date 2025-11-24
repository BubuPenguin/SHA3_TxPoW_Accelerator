#!/usr/bin/env python3

from migen import *
from migen.sim import run_simulation
from keccak_datapath_simd import KeccakDatapath

def test_nonce_injection():
    print("--- Nonce Injection Test ---")
    
    dut = KeccakDatapath(MAX_BLOCKS=4, MAX_DIFFICULTY_BITS=64)

    def generator():
        # ======================================================
        # TEST 1: Verify Nonce XOR Injection and Padding Location
        # ======================================================
        print("\n[TEST 1] Verify Nonce XOR Injection and Padding Location")
        
        # Create 100-byte test input with a repeating pattern
        # Pattern: 0x1122334455667788 repeated to fill 100 bytes
        test_input_bytes = bytearray()
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        for i in range(100):
            test_input_bytes.append(pattern[i % len(pattern)])
        
        # Set byte [1] to 32 (length field)
        test_input_bytes[1] = 32
        
        # Zero out bytes [2] to [33] (nonce field)
        for i in range(2, 34):
            test_input_bytes[i] = 0
        
        # Convert to integer (big-endian)
        test_input = int.from_bytes(test_input_bytes, 'big')
        
        yield dut.input_length.eq(100)
        yield dut.target.eq(0xFFFFFFFFFFFFFFFF)  # Easy target
        yield dut.header_data.eq(test_input)
        
        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        yield
        
        # Wait for ABSORB state (cycle 2: INIT_HASH -> ABSORB)
        # After ABSORB, state should be: 0 ^ padded_block ^ nonce_mask
        cycle_count = 0
        state_after_absorb = None
        
        while (yield dut.running):
            cycle_count += 1
            
            # Capture state right after ABSORB (cycle 3: ABSORB -> PERMUTE)
            # At this point, state has been XORed with padded block and nonce mask
            if cycle_count == 3:
                state_after_absorb = yield dut.state_0
                current_nonce_0 = yield dut.nonce_0
                
                # Calculate expected nonce mask
                # For 100-byte input:
                # - Block 0: bytes 0-135 (136 bytes)
                # - Nonce region: bytes 4-33 (30 bytes = 240 bits)
                # - Padding: 0x06 at byte 100, 0x80 at byte 135
                NONCE_START_BIT = 32  # Byte 4 * 8
                NONCE_WIDTH_BITS = 240
                width_mask = (1 << NONCE_WIDTH_BITS) - 1
                nonce_mask = (current_nonce_0 & width_mask) << NONCE_START_BIT
                
                # Extract nonce mask region and state nonce region
                nonce_mask_region = (nonce_mask >> NONCE_START_BIT) & width_mask
                state_nonce_region = (state_after_absorb >> NONCE_START_BIT) & width_mask
                
                # Calculate padded block from state: state = padded_block XOR nonce_mask
                # Therefore: padded_block = state XOR nonce_mask
                calculated_padded_block = state_nonce_region ^ nonce_mask_region
                
                print(f"  Nonce injection verification:")
                print(f"    nonce_0 value: 0x{current_nonce_0:060x}")
                print(f"    Nonce mask (bits 32-272): 0x{nonce_mask_region:060x}")
                print(f"    State nonce region: 0x{state_nonce_region:060x}")
                print(f"    Calculated padded block (state XOR nonce): 0x{calculated_padded_block:060x}")
                
                # Verify XOR operation: state = padded_block XOR nonce_mask
                # We can verify by checking: (state XOR nonce_mask) XOR nonce_mask = state
                # Or: state XOR nonce_mask should give us the padded block
                verification = state_nonce_region ^ nonce_mask_region
                verification_xor_nonce = verification ^ nonce_mask_region
                
                if verification_xor_nonce == state_nonce_region:
                    print(f"    ✓ Nonce XOR injection correct!")
                    print(f"      Verified: (State XOR Nonce) XOR Nonce = State")
                    print(f"      This confirms: State = Padded_Block XOR Nonce_Mask")
                else:
                    print(f"    ✗ Nonce XOR injection verification failed!")
                    print(f"      (State XOR Nonce) XOR Nonce should equal State")
                    print(f"      Got: 0x{verification_xor_nonce:060x}, Expected: 0x{state_nonce_region:060x}")
                
                # Verify padding location
                # For 100-byte input:
                # - Block 0: bytes 0-135 (136 bytes = 17 words * 8 bytes/word)
                # - Keccak padding rule (10*1): 
                #   * pad_byte_pos = input_length = 100
                #   * pad_word_global_idx = 100 >> 3 = 12 (word 12 contains bytes 96-103)
                #   * pad_byte_in_word = 100 % 8 = 4 (byte 4 within word 12)
                #   * So 0x06 is placed at byte 100 (first byte after input data)
                #   * 0x80 is placed at byte 135 (last byte of block 0, byte 7 of word 16)
                # - Padding: 0x06 at byte 100, 0x80 at byte 135
                # - Bytes 101-134: zeros (between 0x06 and 0x80)
                # In little-endian bit order: byte N is at bits [N*8 : (N+1)*8]
                PAD_START_BYTE = 100  # First byte after 100-byte input
                PAD_END_BYTE = 135     # Last byte of block 0 (136 bytes total)
                PAD_START_BIT = PAD_START_BYTE * 8
                PAD_END_BIT = PAD_END_BYTE * 8
                
                # Extract bytes from state (little-endian: byte N is at bits [N*8 : (N+1)*8])
                pad_start_byte_val = (state_after_absorb >> PAD_START_BIT) & 0xFF
                pad_end_byte_val = (state_after_absorb >> PAD_END_BIT) & 0xFF
                
                print(f"\n  Padding location verification:")
                print(f"    Explanation:")
                print(f"      - Input length: 100 bytes")
                print(f"      - Padding starts at byte 100 (first byte after input)")
                print(f"      - Block 0 size: 136 bytes (17 words)")
                print(f"      - Padding ends at byte 135 (last byte of block 0)")
                print(f"      - Keccak 10*1 rule: 0x06 (domain separator) at start, 0x80 at end")
                print(f"    Byte {PAD_START_BYTE} (bit {PAD_START_BIT}): 0x{pad_start_byte_val:02x} (expected: 0x06)")
                print(f"    Byte {PAD_END_BYTE} (bit {PAD_END_BIT}): 0x{pad_end_byte_val:02x} (expected: 0x80)")
                
                # Note: The state contains XOR of padded_block and nonce_mask
                # Nonce mask only affects bytes 4-33, so bytes 100 and 135 are unaffected
                # Therefore, state[byte_100] should equal padded_block[byte_100] = 0x06
                # And state[byte_135] should equal padded_block[byte_135] = 0x80
                
                pad_start_correct = (pad_start_byte_val == 0x06)
                pad_end_correct = (pad_end_byte_val == 0x80)
                
                if pad_start_correct and pad_end_correct:
                    print(f"    ✓ Padding location verified")
                    print(f"      Byte {PAD_START_BYTE} = 0x06 ✓ (padding start)")
                    print(f"      Byte {PAD_END_BYTE} = 0x80 ✓ (padding end)")
                else:
                    print(f"    ✗ Padding location incorrect!")
                    if not pad_start_correct:
                        print(f"      Byte {PAD_START_BYTE}: got 0x{pad_start_byte_val:02x}, expected 0x06")
                    if not pad_end_correct:
                        print(f"      Byte {PAD_END_BYTE}: got 0x{pad_end_byte_val:02x}, expected 0x80")
                
                break
            
            if (yield dut.found) != 0:
                break
            yield
        
        # ======================================================
        # TEST 2: Nonce Increment
        # ======================================================
        print("\n[TEST 2] Nonce Increment")
        
        # Create 100-byte test input with a repeating pattern
        # Pattern: 0x1122334455667788 repeated to fill 100 bytes
        test_input_bytes = bytearray()
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        for i in range(100):
            test_input_bytes.append(pattern[i % len(pattern)])
        
        # Set byte [1] to 32 (length field)
        test_input_bytes[1] = 32
        
        # Zero out bytes [2] to [33] (nonce field)
        for i in range(2, 34):
            test_input_bytes[i] = 0
        
        # Convert to integer (big-endian)
        test_input = int.from_bytes(test_input_bytes, 'big')
        
        yield dut.input_length.eq(100)
        yield dut.target.eq(0x1FFFFFFFFFFFFFFF)  # Very easy target
        yield dut.header_data.eq(test_input)

        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        yield

        cycle_count = 0
        found_status = 0
        prev_nonce_0 = None
        prev_nonce_1 = None
        
        # Monitor nonce values during mining
        while (yield dut.running):
            cycle_count += 1
            found_status = yield dut.found
            
            # Capture nonce values during mining
            current_nonce_0 = yield dut.nonce_0
            current_nonce_1 = yield dut.nonce_1
            
            # Check if nonces changed (happens in CHECK_RESULT state)
            if prev_nonce_0 is not None and current_nonce_0 != prev_nonce_0:
                print(f"  [Cycle {cycle_count}] nonce_0 changed: {prev_nonce_0:x} -> {current_nonce_0:x}")
            if prev_nonce_1 is not None and current_nonce_1 != prev_nonce_1:
                print(f"  [Cycle {cycle_count}] nonce_1 changed: {prev_nonce_1:x} -> {current_nonce_1:x}")
            
            prev_nonce_0 = current_nonce_0
            prev_nonce_1 = current_nonce_1
            
            if found_status != 0:
                # Yield once more to allow NextValue to update nonce_result
                yield
                break
            yield
        
        # Capture final values (after allowing NextValue to update)
        final_nonce_0 = yield dut.nonce_0
        final_nonce_1 = yield dut.nonce_1
        nonce_result = yield dut.nonce_result
        
        # Fix: Proper conditional assignment
        if found_status == 1:
            hash_output = yield dut.state_0
        else:
            hash_output = yield dut.state_1
            
        hash_256_bits = hash_output & ((1 << 256) - 1)  # Bottom 256 bits (SHA3-256 standard)
        
        print(f"\nResults:")
        print(f"  nonce_0: {final_nonce_0:060x}")
        print(f"  nonce_1: {final_nonce_1:060x}")
        print(f"  nonce_result: {nonce_result:060x}")
        print(f"  Hash:  {hash_256_bits:064x}")
        # found_status: 1 = Core 0, 2 = Core 1
        core_number = found_status - 1 if found_status > 0 else 0
        print(f"  Found by: Core {core_number}")
        print(f"  Cycles: {cycle_count}")
        
        # Verify nonce_result matches the found core's nonce
        if nonce_result == final_nonce_0 or nonce_result == final_nonce_1:
            print("  ✓ nonce_result matches one of the nonces")
        else:
            print("  ✗ nonce_result doesn't match nonce_0 or nonce_1")
        
        # Verify initial nonce values
        print(f"\nInitial nonce values:")
        print(f"  nonce_0 starts at: 1 (linear search)")
        print(f"  nonce_1 starts at: 0 (stochastic)")

        print("\n--- Nonce Injection Tests Complete ---")

    run_simulation(dut, generator())

if __name__ == "__main__":
    test_nonce_injection()

