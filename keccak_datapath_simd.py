from migen import *
from litex.gen import *

from utils import KECCAK_ROUND_CONSTANTS
from keccak_core import KeccakCore
from CountLeadingZero.clz_module import CountLeadingZeros
from FixedIterationStop.fixed_iteration import FixedIterationStop

class KeccakDatapath(LiteXModule):
    """
    SIMD Keccak Datapath (Hybrid Linear + Stochastic)
    
    OPTIMIZATION:
    - Implements "Just-In-Time" Padding.
    - Implements "Early Increment" Pre-fetching to resolve multi-block timing violations.
    - Instead of pre-calculating a massive padded buffer for all blocks,
      it selects the raw block first, then applies padding logic only 
      to the active 1088-bit slice.
    """
    def __init__(self, MAX_BLOCKS=16, MAX_DIFFICULTY_BITS=256, NONCE_DATA_FIELD_OVERWRITE_SPACING=2, NONCE_DATA_FIELD_OVERWRITE_SIZE=30, NONCE_FIELD_BYTE_SIZE=34, NONCE_DATA_FIELD_BYTE_SIZE=32, target_attempts=5000000): 
        # --- Constants ---
        self.NONCE_DATA_FIELD_OVERWRITE_SPACING = NONCE_DATA_FIELD_OVERWRITE_SPACING 
        self.NONCE_DATA_FIELD_OVERWRITE_SIZE = NONCE_DATA_FIELD_OVERWRITE_SIZE
        self.NONCE_DATA_FIELD_BYTE_SIZE = NONCE_DATA_FIELD_BYTE_SIZE
        self.NONCE_FIELD_BYTE_SIZE = NONCE_FIELD_BYTE_SIZE
        self.NONCE_START_BIT = (self.NONCE_FIELD_BYTE_SIZE - self.NONCE_DATA_FIELD_OVERWRITE_SIZE) * 8
        self.NONCE_WIDTH_BITS = self.NONCE_DATA_FIELD_OVERWRITE_SIZE * 8
        self.nonce_field_bits = self.NONCE_DATA_FIELD_BYTE_SIZE * 8

        # --- Standard SHA3-256 parameters ---
        self.RATE_WORDS = 17
        self.BLOCK_BITS = 1088 # 17 * 64
        self.CAPACITY_BITS = 512
        
        # --- Nonce Signals ---
        # Initial values: nonce_0 = 1 (linear search), nonce_1 = 0 (stochastic)
        self.nonce_0 = Signal(self.NONCE_WIDTH_BITS, reset=1)
        self.nonce_1 = Signal(self.NONCE_WIDTH_BITS, reset=0)
        
        # --- Control Interface ---
        self.start = Signal()
        self.stop = Signal()
        self.running = Signal()
        self.found = Signal(2)
        self.idle = Signal() 
        
        self.timeout_limit = Signal(32, reset=0xFFFFFFFF)
        self.timeout = Signal()
        
        # New Attempt Limit (Iterations). 0 = Disable.
        self.attempt_limit = Signal(64)
        self.no_attempts = Signal()
        
        # --- Data Inputs ---
        self.header_data = Signal(self.BLOCK_BITS) 
        self.input_length = Signal(32)  
        self.target_clz = Signal(9, reset=0) # Required minimum CLZ (0 to 256) - number of leading zeros
        
        # --- Results ---
        # Nonce result is 32 bytes (256 bits) = 30-byte nonce + 2-byte header prefix
        self.nonce_result = Signal(self.NONCE_DATA_FIELD_BYTE_SIZE * 8)
        
        # Debug: Expose the first 64 bytes of the current block being processed
        # For Block 0: Shows data with nonce injected (nonce_mask applied)
        # For subsequent blocks: Shows raw block data (nonce_mask is 0)
        # Updated every ABSORB cycle to capture all blocks for verification
        self.debug_block0_data = Signal(512)  # 64 bytes = 512 bits
        
        # --- Internals ---
        self.round_index = Signal(5)
        self.timeout_counter = Signal(32)
        self.attempts_counter = Signal(64)  # 64-bit counter for hash attempts
        self.no_cores = 2 # SIMD-2
        
        # Completion Status (0=None, 1=Found 0, 2=Found 1, 3=Timeout)
        self.completion_status = Signal(2)
        
        # --- FIX: Split Block Logic ---
        # block_addr: Controls the MUX. Increments EARLY (Cycle 0 of Permute)
        # loop_counter: Controls the FSM. Increments LATE (Cycle 23 of Permute)
        self.block_addr = Signal(max=MAX_BLOCKS)
        self.loop_counter = Signal(max=MAX_BLOCKS)
        
        self.total_blocks = Signal(max=MAX_BLOCKS)
        
        self.state_0 = Signal(1600)
        self.state_1 = Signal(1600)
        
        # --- Instantiate Cores ---
        self.submodules.core_0 = KeccakCore()
        self.submodules.core_1 = KeccakCore()
        
        round_consts = Array(Constant(k, 64) for k in KECCAK_ROUND_CONSTANTS)
        self.comb += [
            self.core_0.round_const.eq(round_consts[self.round_index]),
            self.core_1.round_const.eq(round_consts[self.round_index]),
            Cat(*self.core_0.step_input).eq(self.state_0),
            Cat(*self.core_1.step_input).eq(self.state_1),
        ]
        # =========================================================================
        # 1. DYNAMIC BLOCK CALCULATOR
        # =========================================================================
        
        # Determine number of blocks based on input length
        # Simple approach: (len / 136) + 1
        block_calc_stmt = None
        for b in range(MAX_BLOCKS):
            threshold = (b + 1) * 136
            num_blocks = b + 1
            if block_calc_stmt is None:
                block_calc_stmt = If(self.input_length < threshold, self.total_blocks.eq(num_blocks))
            else:
                block_calc_stmt = block_calc_stmt.Elif(self.input_length < threshold, self.total_blocks.eq(num_blocks))
        
        block_calc_stmt = block_calc_stmt.Else(self.total_blocks.eq(MAX_BLOCKS))
        self.comb += block_calc_stmt

        # =========================================================================
        # 2. PIPELINED BLOCK INPUT (BRAM Interface)
        # =========================================================================
        
        # The Controller now handles the BRAM addressing using 'self.block_addr'.
        # 'self.header_data' receives the output of the BRAMs (1088 bits).
        # We simply register this input to cut timing paths between BRAM clock-to-out
        # and the datapath logic.
        
        current_raw_block = Signal(self.BLOCK_BITS)
        
        # REGISTER the input (Pipeline Stage)
        # This gives us a clean cycle for the data to arrive from the BRAM macros.
        self.sync += current_raw_block.eq(self.header_data)
        # =========================================================================
        # 3. LUT PADDING LOGIC (Stage 2)
        # =========================================================================
        
        # LUT is used due to a Migen Translation bug when using arithmetic shifts.
        
        current_block_padded = Signal(self.BLOCK_BITS)
        
        # Padding Parameters
        pad_byte_pos = self.input_length
        pad_word_global_idx = pad_byte_pos >> 3 # Divide by 8
        pad_byte_in_word = pad_byte_pos[0:3]    # Mod 8
        
        # Mask to KEEP existing data bytes (Clear bytes that will be overwritten/zeroed)
        clear_masks = Array([
            Constant(0x0000000000000000, 64),  # Start @ 0: Keep Nothing
            Constant(0x00000000000000FF, 64),  # Start @ 1: Keep Byte 0
            Constant(0x000000000000FFFF, 64),  # Start @ 2: Keep Bytes 0-1
            Constant(0x0000000000FFFFFF, 64),  # Start @ 3: Keep Bytes 0-2
            Constant(0x00000000FFFFFFFF, 64),  # Start @ 4: Keep Bytes 0-3
            Constant(0x000000FFFFFFFFFF, 64),  # Start @ 5: Keep Bytes 0-4
            Constant(0x0000FFFFFFFFFFFF, 64),  # Start @ 6: Keep Bytes 0-5
            Constant(0x00FFFFFFFFFFFFFF, 64),  # Start @ 7: Keep Bytes 0-6
        ])
        
        # Mask to ADD the 0x06 suffix
        set_06_masks = Array([
            Constant(0x0000000000000006, 64),  # 0x06 @ Byte 0
            Constant(0x0000000000000600, 64),  # 0x06 @ Byte 1
            Constant(0x0000000000060000, 64),  # 0x06 @ Byte 2
            Constant(0x0000000006000000, 64),  # 0x06 @ Byte 3
            Constant(0x0000000600000000, 64),  # 0x06 @ Byte 4
            Constant(0x0000060000000000, 64),  # 0x06 @ Byte 5
            Constant(0x0006000000000000, 64),  # 0x06 @ Byte 6
            Constant(0x0600000000000000, 64),  # 0x06 @ Byte 7
        ])
        
        # Use Signals with comb assignments to avoid Migen arithmetic shift bug
        pad_clear_mask = Signal(64)
        pad_set_06 = Signal(64)
        pad_set_80 = Signal(64)
        
        # Use array indexing instead of variable shifts to avoid arithmetic shift bug
        self.comb += [
            pad_clear_mask.eq(clear_masks[pad_byte_in_word]),
            pad_set_06.eq(set_06_masks[pad_byte_in_word]),
            pad_set_80.eq(Constant(0x8000000000000000, 64)),  # 0x80 at byte 7
        ]

        # Calculate last word index of the ENTIRE message
        last_word_of_message_idx = (self.total_blocks * 17) - 1

        # Iterate over the 17 words in the CURRENT block
        for i in range(self.RATE_WORDS):
            
            # Calculate the Global Index of this word
            # (Current Block * 17) + i
            # FIX: Calculate global index based on block_addr
            global_word_idx = (self.block_addr * 17) + i
            
            raw_word = current_raw_block[i*64 : (i+1)*64]
            word_out = Signal(64)
            
            # Conditions
            is_pad_start_word = (global_word_idx == pad_word_global_idx)
            is_msg_end_word   = (global_word_idx == last_word_of_message_idx)
            is_after_pad      = (global_word_idx > pad_word_global_idx)
            
            self.comb += [
                # Case A: Collision - Padding Start (0x06) and Block End (0x80) in same word
                If(is_pad_start_word & is_msg_end_word,
                    word_out.eq((raw_word & pad_clear_mask) | pad_set_06 | pad_set_80)
                
                # Case B: Standard Padding Start (0x06)
                ).Elif(is_pad_start_word,
                    word_out.eq((raw_word & pad_clear_mask) | pad_set_06)
                
                # Case C: Block End (0x80) - only if this is the actual last word of message
                ).Elif(is_msg_end_word,
                    word_out.eq(pad_set_80)
                
                # Case D: Zero Fill Area (Between 0x06 and 0x80)
                ).Elif(is_after_pad,
                    word_out.eq(0)
                
                # Case E: Standard Data
                ).Else(
                    word_out.eq(raw_word)
                )
            ]
            
            self.comb += current_block_padded[i*64 : (i+1)*64].eq(word_out)

        # =========================================================================
        # 4. FSM
        # =========================================================================
        self.submodules.fsm = FSM(reset_state="IDLE")
        
        # Extend the 1088-bit Rate slice to full 1600-bit State
        padded_slice_extended = Signal(1600)
        self.comb += padded_slice_extended.eq(Cat(current_block_padded, Constant(0, 512)))
        
        # Nonce Masks (Only applied to Block 0)
        # FIX: Use Cat() instead of shift to avoid Migen shift translation bug
        # The nonce is inserted at bit position NONCE_START_BIT (32)
        nonce_mask_0 = Signal(1600)
        nonce_mask_1 = Signal(1600)
        width_mask = Constant((1 << self.NONCE_WIDTH_BITS) - 1, self.NONCE_WIDTH_BITS)
        
        # Masked nonce values
        masked_nonce_0 = Signal(self.NONCE_WIDTH_BITS)
        masked_nonce_1 = Signal(self.NONCE_WIDTH_BITS)
        self.comb += [
            masked_nonce_0.eq(self.nonce_0 & width_mask),
            masked_nonce_1.eq(self.nonce_1 & width_mask)
        ]

        # FIX: Check block_addr here. In ABSORB, block_addr is correct (0).
        self.comb += [
            If(self.block_addr == 0,
                nonce_mask_0.eq(Cat(
                    Constant(0, self.NONCE_START_BIT),
                    masked_nonce_0,
                    Constant(0, 1600 - self.NONCE_START_BIT - self.NONCE_WIDTH_BITS)
                )),
                nonce_mask_1.eq(Cat(
                    Constant(0, self.NONCE_START_BIT),
                    masked_nonce_1,
                    Constant(0, 1600 - self.NONCE_START_BIT - self.NONCE_WIDTH_BITS)
                ))
            ).Else(
                nonce_mask_0.eq(0),
                nonce_mask_1.eq(0)
            )
        ]
        
        # =========================================================================
        # 5. RESULT EXTRACTION & COMPARISON (CLZ VERSION)
        # =========================================================================
        
        # Extract the Raw Hash (Bottom 256 bits)
        raw_hash_0 = self.state_0[0:MAX_DIFFICULTY_BITS]
        raw_hash_1 = self.state_1[0:MAX_DIFFICULTY_BITS]
        
        # Instantiate CLZ modules for both cores
        self.submodules.clz_0 = CountLeadingZeros(width=MAX_DIFFICULTY_BITS)
        self.submodules.clz_1 = CountLeadingZeros(width=MAX_DIFFICULTY_BITS)
        
        # Connect hash inputs to CLZ modules
        self.comb += [
            self.clz_0.i.eq(raw_hash_0),
            self.clz_1.i.eq(raw_hash_1),
        ]
        
        # OPTIONAL: Keep FixedIterationStop for testing (commented out)
        # To use fixed iteration mode instead of real difficulty:
        # self.submodules.clz_0 = FixedIterationStop(target_iterations=target_iterations)
        # self.submodules.clz_1 = FixedIterationStop(target_iterations=target_iterations)
        # self.comb += [
        #     self.clz_0.i.eq(raw_hash_0),
        #     self.clz_0.iteration.eq(self.iteration_counter),
        #     self.clz_1.i.eq(raw_hash_1),
        #     self.clz_1.iteration.eq(self.iteration_counter),
        # ]
        
        # Expose CLZ outputs for debug
        self.clz_0_out = Signal(9)  # 9 bits for 0 to 256
        self.clz_1_out = Signal(9)  # 9 bits for 0 to 256
        self.comb += [
            self.clz_0_out.eq(self.clz_0.o),
            self.clz_1_out.eq(self.clz_1.o),
        ]
        
        # Preserve signals for debugging
        self.clz_0_out.attr.add(("keep", "true"))
        self.clz_1_out.attr.add(("keep", "true"))
        self.target_clz.attr.add(("keep", "true"))
        
        # For backward compatibility with debug_comparison register (now CLZ >= target_clz)
        self.hash0_lt_target = Signal()
        self.hash1_lt_target = Signal()
        self.comb += [
            self.hash0_lt_target.eq(self.clz_0_out >= self.target_clz),
            self.hash1_lt_target.eq(self.clz_1_out >= self.target_clz)
        ]
        self.hash0_lt_target.attr.add(("keep", "true"))
        self.hash1_lt_target.attr.add(("keep", "true"))
        
        # Increment timeout counter every cycle when running (not in IDLE or DONE states)
        # This ensures timeout is measured in clock cycles, not iterations
        self.sync += [
            If(self.running,
                self.timeout_counter.eq(self.timeout_counter + 1)
            )
        ]
        
        self.fsm.act("IDLE",
            self.running.eq(0),
            self.found.eq(0),
            self.idle.eq(1),
            
            # Optimization: Reset block_addr to 0 in IDLE.
            # This ensures that while we wait for Start, the BRAMs are reading Block 0,
            # and the pipeline register 'current_raw_block' catches it.
            # By the time we start, Block 0 is already valid!
            NextValue(self.block_addr, 0),
            
            # Only start if the Start signal is asserted
            If(self.start,
                # Clear status signals when starting new hash
                NextValue(self.found, 0),
                NextValue(self.timeout, 0), 
                NextValue(self.completion_status, 0), # Reset status
                NextValue(self.timeout_counter, 0),
                NextValue(self.attempts_counter, 0),  # Reset attempts counter
                self.timeout.eq(0),
                self.no_attempts.eq(0),
                NextValue(self.nonce_0, 1),
                NextValue(self.nonce_1, 0),
                NextState("INIT_HASH")
            )
        )
        
        self.fsm.act("INIT_HASH",
            self.running.eq(1),
            self.idle.eq(0),
            NextValue(self.state_0, 0),
            NextValue(self.state_1, 0),
            # block_addr is already 0 from IDLE or CHECK_RESULT
            NextValue(self.loop_counter, 0),
            # Direct transition to ABSORB because pipeline is primed
            NextState("ABSORB") 
        )
        
        self.fsm.act("ABSORB",
            self.running.eq(1),
            self.idle.eq(0),
            NextValue(self.state_0, self.state_0 ^ padded_slice_extended ^ nonce_mask_0),
            NextValue(self.state_1, self.state_1 ^ padded_slice_extended ^ nonce_mask_1),
            NextValue(self.round_index, 0),
            # Debug: Capture first 512 bits of current block for every iteration
            # Block 0: padded_slice_extended ^ nonce_mask_0 (shows nonce injection)
            # Block 1+: padded_slice_extended (nonce_mask_0 is 0, shows raw data)
            NextValue(self.debug_block0_data, (padded_slice_extended ^ nonce_mask_0)[0:512]),
            NextState("PERMUTE")
        )
        
        self.fsm.act("PERMUTE",
            self.running.eq(1),
            self.idle.eq(0),
            NextValue(self.state_0, Cat(*self.core_0.iota_out)),
            NextValue(self.state_1, Cat(*self.core_1.iota_out)),
            
            # --- FIX: EARLY INCREMENT LOGIC ---
            # At Round 0, check if we will need another block later.
            # If so, increment the address NOW. This gives the MUX 23 cycles 
            # to switch and settle before we reach ABSORB again.
            If((self.round_index == 0) & (self.block_addr < self.total_blocks - 1),
                NextValue(self.block_addr, self.block_addr + 1)
            ),
            
            If(self.round_index == 23,
                # At Round 23, we use loop_counter to control the flow.
                If((self.loop_counter + 1) < self.total_blocks,
                    NextValue(self.loop_counter, self.loop_counter + 1),
                    NextState("ABSORB") 
                ).Else(
                    NextState("CHECK_RESULT")
                )
            ).Else(
                NextValue(self.round_index, self.round_index + 1),
                NextState("PERMUTE")
            )
        )
        
        self.fsm.act("CHECK_RESULT",
            self.running.eq(1),
            self.idle.eq(0),
            
            # CHECK DIFFICULTY using the CLZ (Count Leading Zeros)
            # If (CLZ of hash >= required CLZ) then we have a potential solution.
            
            # Check timeout FIRST (before checking results) to ensure cycle limit is enforced
            If((self.timeout_limit != 0) & (self.timeout_counter >= self.timeout_limit),
                NextValue(self.completion_status, 3), # Timeout
                NextState("DONE")
            # Check attempt limit (NoAttempt)
            ).Elif((self.attempt_limit != 0) & (self.attempts_counter >= self.attempt_limit),
                NextValue(self.completion_status, 4), # NoAttempt (Exhausted)
                NextState("DONE")
            ).Elif(self.clz_0_out >= self.target_clz,
                NextValue(self.nonce_result, Cat(self.header_data[16:32], self.nonce_0)),
                NextValue(self.completion_status, 1), # Found 0
                NextState("DONE") 
            ).Elif(self.clz_1_out >= self.target_clz,
                NextValue(self.nonce_result, Cat(self.header_data[16:32], self.nonce_1)),
                NextValue(self.completion_status, 2), # Found 1
                NextState("DONE")
            ).Elif(self.stop,
                NextState("IDLE")
            ).Else(
                NextValue(self.nonce_0, self.nonce_0 + 1),
                NextValue(self.nonce_1, self.state_0[0:self.NONCE_WIDTH_BITS]), # Stochastic update
                NextValue(self.attempts_counter, self.attempts_counter + self.no_cores),
                
                # When restarting loop, we must reset block_addr to 0.
                NextValue(self.block_addr, 0),
                
                NextState("INIT_HASH")
            )
        )
        
        # --- NEW HANDSHAKE STATE ---
        # Consolidated state for all completion types (Found 0, Found 1, Timeout, NoAttempt)
        # Holds the result signals until software clears 'start'
        
        self.fsm.act("DONE",
            self.running.eq(0),
            self.idle.eq(0),
            
            # Drive outputs based on the stored completion status
            If(self.completion_status == 1,      # Found 0
                self.found.eq(1)
            ).Elif(self.completion_status == 2,  # Found 1
                self.found.eq(2)
            ).Elif(self.completion_status == 3,  # Timeout
                self.timeout.eq(1)
            ).Elif(self.completion_status == 4,  # NoAttempt
                self.no_attempts.eq(1)
            ),
            
            # Wait for handshake
            If(~self.start, NextState("IDLE"))
        )
