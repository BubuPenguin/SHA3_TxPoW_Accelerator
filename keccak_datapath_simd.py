from migen import *
from litex.gen import *

from utils import KECCAK_ROUND_CONSTANTS
from keccak_core import KeccakCore

class KeccakDatapath(LiteXModule):
    """
    SIMD Keccak Datapath (Hybrid Linear + Stochastic)
    
    OPTIMIZATION:
    - Implements "Just-In-Time" Padding.
    - Instead of pre-calculating a massive padded buffer for all blocks,
      it selects the raw block first, then applies padding logic only 
      to the active 1088-bit slice.
    """
    def __init__(self, MAX_BLOCKS=16, MAX_DIFFICULTY_BITS=128, NONCE_DATA_FIELD_OVERWRITE_LOCATION=4, NONCE_DATA_FIELD_OVERWRITE_SIZE=30, NONCE_FIELD_BYTE_SIZE=34): 
        # --- Constants ---
        self.NONCE_DATA_FIELD_OVERWRITE_LOCATION = NONCE_DATA_FIELD_OVERWRITE_LOCATION 
        self.NONCE_DATA_FIELD_OVERWRITE_SIZE = NONCE_DATA_FIELD_OVERWRITE_SIZE
        self.NONCE_FIELD_BYTE_SIZE = NONCE_FIELD_BYTE_SIZE

        self.NONCE_START_BIT = self.NONCE_DATA_FIELD_OVERWRITE_LOCATION * 8
        self.NONCE_WIDTH_BITS = self.NONCE_DATA_FIELD_OVERWRITE_SIZE * 8
        self.nonce_field_bits = self.NONCE_FIELD_BYTE_SIZE * 8

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
        
        self.timeout_limit = Signal(32)
        self.timeout = Signal()
        
        # --- Data Inputs ---
        self.header_data = Signal(self.BLOCK_BITS * MAX_BLOCKS) 
        self.input_length = Signal(32)  
        self.target = Signal(MAX_DIFFICULTY_BITS)
        
        # --- Results ---
        self.nonce_result = Signal(self.nonce_field_bits)
        
        # --- Internals ---
        self.round_index = Signal(5)
        self.timeout_counter = Signal(32)
        
        self.block_counter = Signal(max=MAX_BLOCKS)
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
        # 2. RAW BLOCK SELECTOR (Stage 1)
        # =========================================================================
        
        # First, simply select the raw data relevant to the current block counter.
        # This creates one MUX for the raw data, rather than calculating padding for ALL data.
        
        current_raw_block = Signal(self.BLOCK_BITS)
        block_cases = {}
        for b in range(MAX_BLOCKS):
            block_cases[b] = current_raw_block.eq(self.header_data[b*self.BLOCK_BITS : (b+1)*self.BLOCK_BITS])
        
        self.comb += Case(self.block_counter, block_cases)

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
            # FIX: Use multiplication instead of shift to avoid Migen arithmetic shift bug
            global_word_idx = (self.block_counter * 17) + i
            
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

        self.comb += [
            If(self.block_counter == 0,
                # Use Cat() to build the mask: [padding_low, nonce, padding_high]
                # nonce_mask = {padding_high, nonce, padding_low}
                nonce_mask_0.eq(Cat(
                    Constant(0, self.NONCE_START_BIT),           # Bits 0-31: zeros
                    masked_nonce_0,                               # Bits 32-271: nonce (240 bits)
                    Constant(0, 1600 - self.NONCE_START_BIT - self.NONCE_WIDTH_BITS)  # Bits 272-1599: zeros
                )),
                nonce_mask_1.eq(Cat(
                    Constant(0, self.NONCE_START_BIT),           # Bits 0-31: zeros
                    masked_nonce_1,                               # Bits 32-271: nonce (240 bits)
                    Constant(0, 1600 - self.NONCE_START_BIT - self.NONCE_WIDTH_BITS)  # Bits 272-1599: zeros
                ))
            ).Else(
                nonce_mask_0.eq(0),
                nonce_mask_1.eq(0)
            )
        ]
        
        # Extract bottom MAX_DIFFICULTY_BITS from 1600-bit state for difficulty comparison
        # SHA3-256 uses the first 256 bits (LSBs) of the state as the hash output
        # For 128-bit difficulty: state[0:128] extracts bits 0-127 (bottom 128 bits)
        state_0_top_bits = Signal(MAX_DIFFICULTY_BITS)
        state_1_top_bits = Signal(MAX_DIFFICULTY_BITS)
        
        # Calculate slice bounds (Python arithmetic, evaluated at construction time)
        # Extract from bottom (LSBs) for SHA3-256 standard
        slice_low = 0
        slice_high = MAX_DIFFICULTY_BITS
        
        self.comb += [
            state_0_top_bits.eq(self.state_0[slice_low:slice_high]),
            state_1_top_bits.eq(self.state_1[slice_low:slice_high])
        ]

        self.fsm.act("IDLE",
            self.running.eq(0),
            self.found.eq(0),
            If(self.start,
                NextValue(self.nonce_0, 1),
                NextValue(self.nonce_1, 0),
                NextValue(self.timeout_counter, 0),
                self.timeout.eq(0),
                NextState("INIT_HASH")
            )
        )
        
        self.fsm.act("INIT_HASH",
            self.running.eq(1),
            NextValue(self.state_0, 0),
            NextValue(self.state_1, 0),
            NextValue(self.block_counter, 0),
            NextState("ABSORB")
        )
        
        self.fsm.act("ABSORB",
            self.running.eq(1),
            # XOR Data into State
            NextValue(self.state_0, self.state_0 ^ padded_slice_extended ^ nonce_mask_0),
            NextValue(self.state_1, self.state_1 ^ padded_slice_extended ^ nonce_mask_1),
            NextValue(self.round_index, 0),
            NextState("PERMUTE")
        )
        
        self.fsm.act("PERMUTE",
            self.running.eq(1),
            NextValue(self.state_0, Cat(*self.core_0.iota_out)),
            NextValue(self.state_1, Cat(*self.core_1.iota_out)),
            
            If(self.round_index == 23,
                If((self.block_counter + 1) < self.total_blocks,
                    NextValue(self.block_counter, self.block_counter + 1),
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
            NextValue(self.timeout_counter, self.timeout_counter + 1),
            
            If(state_0_top_bits < self.target,
                NextValue(self.nonce_result, self.nonce_0),
                self.found.eq(1),
                NextState("IDLE")
            ).Elif(state_1_top_bits < self.target,
                NextValue(self.nonce_result, self.nonce_1),
                self.found.eq(2),
                NextState("IDLE")
            ).Elif(self.stop,
                NextState("IDLE")
            ).Elif((self.timeout_limit != 0) & (self.timeout_counter >= self.timeout_limit),
                self.timeout.eq(1),
                NextState("IDLE")
            ).Else(
                NextValue(self.nonce_0, self.nonce_0 + 1),
                NextValue(self.nonce_1, self.state_1[0:self.NONCE_WIDTH_BITS]),
                NextState("INIT_HASH")
            )
        )