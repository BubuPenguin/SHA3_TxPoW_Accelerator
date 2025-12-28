from migen import *
from litex.gen import *
from litex.soc.interconnect.csr import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourcePulse
from litex.soc.interconnect import wishbone
from litex.soc.cores.dma import WishboneDMAReader

import math
import os
import sys

# Add current directory to path for imports when used as a package
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from keccak_datapath_simd import KeccakDatapath

# --- Configuration Macros ---

# 1. Header Structure
# Increased to 2048 bytes as requested
HEADER_SIZE_BYTES = 2176 #For 2kb, 16*136 bytes
BLOCK_SIZE_BYTES = 136 #64 bits

WORD_WIDTH        = 64 #64 bits
WORD_BYTES        = WORD_WIDTH // 8 
HEADER_WORDS      = HEADER_SIZE_BYTES // WORD_BYTES

MAX_BLOCKS = (HEADER_SIZE_BYTES + BLOCK_SIZE_BYTES - 1) // BLOCK_SIZE_BYTES #16 blocks

# 2. Difficulty & Nonce Parameters
MAX_DIFFICULTY_BITS = 256

# The Nonce Field Size (34 Bytes)
MNONCE_FIELD_BYTE_SIZE = 34 
MNONCE_SCALE_FIELD_LOCATION = 0 
MNONCE_LENGTH_FIELD_LOCATION = 1 

MNONCE_DATA_FIELD_BYTE_SIZE = 32
MNONCE_DATA_FIELD_OVERWRITE_SPACING = 2 #Spacing between the nonce data field and the nonce start field
MNONCE_DATA_FIELD_OVERWRITE_SIZE = MNONCE_DATA_FIELD_BYTE_SIZE - MNONCE_DATA_FIELD_OVERWRITE_SPACING 

class SHA3TxPoWController(LiteXModule):
    """
    SHA3 TxPoW Controller (Optimized, Hybrid, Timeout, with DMA support).
    
    FIX: Uses atomic write capture to prevent timing issues where
    the write address increments before the data is consumed.
    """
    def __init__(self, target_iterations=5000000):
        # --- CSR Definitions ---
        self._control = CSRStorage(2, description="Control Register [0:Start, 1:Stop]")
        self._status  = CSRStatus(4, description="Status Register [0:Idle, 1:Running, 2:Found, 3:Timeout]")
        
        self._nonce_result = CSRStatus(MNONCE_DATA_FIELD_BYTE_SIZE * 8, description="Result Nonce")
        self._hash_result  = CSRStatus(256, description="Hash Output (SHA3-256, 32 bytes)")
        self._iteration_count = CSRStatus(64, description="Number of hash iterations performed")
        self._target_clz = CSRStorage(9, description="Target Difficulty (CLZ: number of leading zeros, 0-256)")
        
        # Debug CSRs (Solution 2 from EXECUTIVE_SUMMARY)
        self._debug_hash0 = CSRStatus(MAX_DIFFICULTY_BITS, description="Debug: Hash 0 (raw)")
        self._debug_hash1 = CSRStatus(MAX_DIFFICULTY_BITS, description="Debug: Hash 1 (raw)")
        self._debug_clz0 = CSRStatus(9, description="Debug: CLZ of Hash 0 (actual leading zeros)")
        self._debug_clz1 = CSRStatus(9, description="Debug: CLZ of Hash 1 (actual leading zeros)")
        self._debug_comparison = CSRStatus(2, description="Debug: comparison results [0:hash0_lt, 1:hash1_lt]")
        
        # Debug: Expose first 64 bytes of block 0 after nonce injection (for verification)
        # This shows the nonce area and some context (bytes 0-63)
        self._debug_block0_data = CSRStatus(512, description="Debug: Block 0 first 64 bytes (bits [511:0])")
        
        self._timeout = CSRStorage(64, description="Timeout Limit (Clock Cycles). 0=Disable")
        
        # Input Length for Padding
        self._input_len = CSRStorage(32, description="Length of input header in bytes")
        
        # Header Data Window - Split into two 32-bit registers for proper endianness
        # Low 32 bits go to first address, High 32 bits to second address
        self._header_data_low  = CSRStorage(32, description="Header Data (Low 32)")
        self._header_data_high = CSRStorage(32, description="Header Data (High 32)")
        
        # Combine them (Low bits first, as per little-endian convention)
        combined_header = Cat(self._header_data_low.storage, self._header_data_high.storage)
        
        # Dynamic address width calculation
        addr_width = int(math.ceil(math.log2(HEADER_WORDS)))
        self._header_addr = CSRStorage(addr_width, description=f"Header Address (0-{HEADER_WORDS-1})") 
        
        self._header_we   = CSRStorage(1, description="Header Write Enable")
        
        # --- Wishbone Master Interface for DMA ---
        self.bus = wishbone.Interface(data_width=64)
        
        # Interrupts (Found OR Timeout)
        self.submodules.ev = EventManager()
        self.ev.found   = EventSourcePulse(description="Valid Nonce Found")
        self.ev.timeout = EventSourcePulse(description="Mining Timed Out")
        self.ev.finalize()
        
        # --- Instantiate DMA Reader ---
        self.submodules.dma = WishboneDMAReader(self.bus, endianness="little", fifo_depth=16, with_csr=True)
        
        # --- Instantiate Miner ---
        self.submodules.miner = KeccakDatapath(
            MAX_BLOCKS=MAX_BLOCKS,
            MAX_DIFFICULTY_BITS=MAX_DIFFICULTY_BITS,
            NONCE_DATA_FIELD_OVERWRITE_SPACING=MNONCE_DATA_FIELD_OVERWRITE_SPACING,
            NONCE_DATA_FIELD_OVERWRITE_SIZE=MNONCE_DATA_FIELD_OVERWRITE_SIZE,
            NONCE_FIELD_BYTE_SIZE=MNONCE_FIELD_BYTE_SIZE,
            NONCE_DATA_FIELD_BYTE_SIZE=MNONCE_DATA_FIELD_BYTE_SIZE,
            target_iterations=target_iterations
        )
        
        # --- Header Storage ---
        # Single unified 2176-byte memory (272 x 64-bit words)
        header_memory = Memory(width=WORD_WIDTH, depth=HEADER_WORDS, init=None)
        self.specials += header_memory
        
        # Write port (supports both DMA and CSR writes)
        header_write_port = header_memory.get_port(write_capable=True, we_granularity=0)
        self.specials += header_write_port
        
        # Read ports for all words (needed to concatenate entire memory)
        # Create read signals for each word
        header_read_data = Array(Signal(WORD_WIDTH) for _ in range(HEADER_WORDS))
        
        # Create read ports for each word (combinational reads)
        for i in range(HEADER_WORDS):
            read_port = header_memory.get_port()
            self.specials += read_port
            # Set address to word index
            self.comb += read_port.adr.eq(i)
            # Capture read data
            self.comb += header_read_data[i].eq(read_port.dat_r)
        
        # --- Header Storage Write Logic (CSR and DMA) ---
        
        # =========================================================================
        # UNIFIED WRITE LOGIC
        # =========================================================================
        
        # Track DMA write address (exposed for debugging)
        self.dma_write_addr = dma_write_addr = Signal(addr_width)
        
        # Detect rising edge of DMA enable to reset the write pointer
        self.dma_enable_d = dma_enable_d = Signal()
        dma_enable_rising = Signal()
        self.sync += dma_enable_d.eq(self.dma._enable.storage)
        self.comb += dma_enable_rising.eq(~dma_enable_d & self.dma._enable.storage)
        
        # DMA ready signal: always ready when DMA is enabled
        # The DMA controller handles length checking internally
        self.comb += self.dma.source.ready.eq(self.dma._enable.storage)
        
        # Update write address on handshake
        self.sync += [
            If(dma_enable_rising,
                dma_write_addr.eq(0)
            ).Elif(self.dma.source.valid & self.dma.source.ready,
                dma_write_addr.eq(dma_write_addr + 1)
            )
        ]
        
        # Unified write port logic
        # Priority 1: DMA write (immediate, no pipeline delay)
        # Priority 2: CSR write (Manual) - Use combined_header (Low bits first)
        write_addr = Signal(addr_width)
        write_data = Signal(WORD_WIDTH)
        write_enable = Signal()
        
        self.comb += [
            # Determine write address and data based on priority
            If(self.dma.source.valid & self.dma.source.ready,
                write_addr.eq(dma_write_addr),
                write_data.eq(self.dma.source.data),
                write_enable.eq(1)
            ).Elif(self._header_we.storage,
                write_addr.eq(self._header_addr.storage),
                write_data.eq(combined_header),
                write_enable.eq(1)
            ).Else(
                write_enable.eq(0)
            ),
            # Connect to memory write port
            header_write_port.adr.eq(write_addr),
            header_write_port.dat_w.eq(write_data),
            header_write_port.we.eq(write_enable)
        ]
        
        # =========================================================================
        
        # Connect flattened storage to miner input
        self.comb += self.miner.header_data.eq(Cat(*header_read_data))
        
        # --- Control & Status ---
        self.comb += [
            self.miner.target_clz.eq(self._target_clz.storage),
            self.miner.timeout_limit.eq(self._timeout.storage),
            self.miner.input_length.eq(self._input_len.storage), 
            
            self.miner.start.eq(self._control.storage[0]),
            self.miner.stop.eq(self._control.storage[1]),
            
            # Status Mapping
            self._status.status[0].eq(self.miner.idle),
            self._status.status[1].eq(self.miner.running),
            self._status.status[2].eq(self.miner.found != 0),
            self._status.status[3].eq(self.miner.timeout),
            
            # Connect the miner result to the CSR status
            # Nonce result is 32 bytes (256 bits) - read directly from miner.nonce_result
            # The datapath handles concatenation with header_data bytes [2:3]
            self._nonce_result.status.eq(self.miner.nonce_result[0:256]),
            self._iteration_count.status.eq(self.miner.iteration_counter),
            
            # Debug CSRs (Solution 2 from EXECUTIVE_SUMMARY)
            # Expose internal comparison values for debugging
            # Use raw hash (bottom 256 bits of state) for debug registers
            self._debug_hash0.status.eq(self.miner.state_0[0:256]),
            self._debug_hash1.status.eq(self.miner.state_1[0:256]),
            self._debug_clz0.status.eq(self.miner.clz_0_out),
            self._debug_clz1.status.eq(self.miner.clz_1_out),
            self._debug_comparison.status[0].eq(self.miner.hash0_lt_target),
            self._debug_comparison.status[1].eq(self.miner.hash1_lt_target),
            
            # Debug: Expose first 64 bytes of block 0 data (512 bits)
            # This captures the nonce area with context
            self._debug_block0_data.status.eq(self.miner.debug_block0_data[0:512]),
        ]
        
        # --- FIX START ---
        # Create a latch to hold the result hash.
        # With handshake states, self.miner.found is held high until start is cleared,
        # but we latch the hash when found first goes high for stability.
        self.last_hash = Signal(256)
        
        self.sync += [
            If(self.miner.found == 1,
                self.last_hash.eq(self.miner.state_0[0:256])
            ).Elif(self.miner.found == 2,
                self.last_hash.eq(self.miner.state_1[0:256])
            )
            # No Else: Retain value until next solution is found
        ]
        
        self.comb += self._hash_result.status.eq(self.last_hash)
        # --- FIX END ---
        
        # Trigger interrupts
        self.comb += [
            self.ev.found.trigger.eq(self.miner.found != 0),
            self.ev.timeout.trigger.eq(self.miner.timeout)
        ]