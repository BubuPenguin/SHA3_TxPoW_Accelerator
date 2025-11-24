#!/usr/bin/env python3

from migen import *
from migen.sim import run_simulation
from keccak_datapath_simd import KeccakDatapath

def debug_multiblock():
    print("--- Debugging Multi-Block Processing ---")
    
    # Initialize DUT
    dut = KeccakDatapath(MAX_BLOCKS=4, MAX_DIFFICULTY_BITS=128)

    def generator():
        # 1. Setup Input (300 Bytes)
        test_input_bytes = bytearray()
        pattern = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        for i in range(300):
            test_input_bytes.append(pattern[i % len(pattern)])
        
        test_input_bytes[1] = 32 # Length
        for i in range(2, 34):   # Clear Nonce
            test_input_bytes[i] = 0
            
        # Load as Little Endian
        test_input = int.from_bytes(test_input_bytes, 'little')
        
        yield dut.input_length.eq(300)
        yield dut.target.eq(0x0FFFFFFFFFFFFFFF) 
        yield dut.header_data.eq(test_input)

        yield dut.start.eq(1)
        yield
        yield dut.start.eq(0)
        yield

        print(f"\n[DEBUG START]")
        
        # Capture Initial Configuration
        calc_total_blocks = yield dut.total_blocks
        input_len_sig = yield dut.input_length
        print(f"  Signal input_length: {input_len_sig}")
        print(f"  Signal total_blocks: {calc_total_blocks} (Expected: 3)")
        
        if calc_total_blocks != 3:
            print("  [CRITICAL ERROR] total_blocks is incorrect! This explains the early finish.")
            print("  Check MAX_BLOCKS signal width or threshold logic.")

        cycle_count = 0
        prev_state_0 = 0
        
        while (yield dut.running):
            cycle_count += 1
            
            # --- Monitor ABSORB Phase ---
            # We detect the ABSORB phase by looking at round_index.
            # In ABSORB, the FSM sets round_index to 0.
            # In the very next cycle (First cycle of PERMUTE), we can read the state.
            
            curr_round = yield dut.round_index
            curr_block = yield dut.block_counter
            
            # If we are in Round 0, we just finished absorbing.
            if curr_round == 0:
                curr_state_0 = yield dut.state_0
                
                # Recover the block data by XORing current state with previous state
                # Block = New_State ^ Old_State
                absorbed_data = curr_state_0 ^ prev_state_0
                
                print(f"\n  [Block {curr_block}] Absorbed Data Trace:")
                print(f"    Cycle: {cycle_count}")
                
                # Convert to bytes (Little Endian) to show what the hardware saw
                # We show the first 32 bytes to check the header
                try:
                    block_bytes = absorbed_data.to_bytes(200, 'little') # 1600 bits = 200 bytes
                    # The block is only 136 bytes (1088 bits)
                    data_slice = block_bytes[0:136]
                    
                    print(f"    Raw Hex (First 32 bytes): {data_slice[0:32].hex()}")
                    
                    # Verify Header Bytes
                    scale = data_slice[0]
                    length = data_slice[1]
                    print(f"    Byte 0 (Scale):  0x{scale:02x}")
                    print(f"    Byte 1 (Length): 0x{length:02x}")
                    
                    # Check Padding for this block
                    # 0x06 should be at byte 100 IF this is the block containing byte 100
                    # For block 0, it contains bytes 0-135.
                    # Input is 300 bytes.
                    # Block 0: Bytes 0-135 (Data)
                    # Block 1: Bytes 136-271 (Data)
                    # Block 2: Bytes 272-299 (Data) + Padding at 300
                    
                    if curr_block == 0:
                        print("    Block 0 Analysis: Should contain Start of Header")
                    elif curr_block == 1:
                        print("    Block 1 Analysis: Should contain Middle Data")
                    elif curr_block == 2:
                        print("    Block 2 Analysis: Should contain End of Data + Padding")
                        # Check padding location relative to block start (272)
                        # Padding is at 300. 300 - 272 = 28.
                        # So byte 28 of this block should be 0x06.
                        print(f"    Byte 28 (Padding Start?): 0x{data_slice[28]:02x}")
                        print(f"    Byte 135 (Block End?):    0x{data_slice[135]:02x}")
                        
                except Exception as e:
                    print(f"    Error analyzing block: {e}")

                # Save state for next diff
                # Note: The state changes during permutation. We need the state *at the end of permutation*
                # to diff against the *next* absorb.
                # Ideally, we track the cumulative XORs.
                # However, since permutation scrambles the state, we can't simply XOR 
                # state_after_permute ^ state_after_next_absorb to get the block.
                # We specifically need to probe the "padded_slice" signal, but we can't easily access internal signals here.
                # BUT, we can see if the `absorbed_data` we calculated looks like valid ASCII/Data or scrambled garbage.
                
                # Wait... correct logic:
                # State_After_Absorb = State_After_Permute_Prev ^ Block_Data
                # So Block_Data = State_After_Absorb ^ State_After_Permute_Prev
                # We need to capture State_After_Permute_Prev.
                pass

            # Capture state at the very end of a round sequence (Round 23)
            # This will be the "Prev State" for the NEXT block's absorb
            if curr_round == 23:
                 prev_state_0 = yield dut.state_0

            # Exit if done
            if (yield dut.found) != 0:
                break
            yield

    run_simulation(dut, generator())

if __name__ == "__main__":
    debug_multiblock()