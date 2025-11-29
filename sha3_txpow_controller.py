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
HEADER_SIZE_BYTES = 2048 #2kB
BLOCK_SIZE_BYTES = 136 #64 bits

WORD_WIDTH        = 64 #64 bits
WORD_BYTES        = WORD_WIDTH // 8 
HEADER_WORDS      = HEADER_SIZE_BYTES // WORD_BYTES

MAX_BLOCKS = (HEADER_SIZE_BYTES + BLOCK_SIZE_BYTES - 1) // BLOCK_SIZE_BYTES #16 blocks

# 2. Difficulty & Nonce Parameters
# Target is now 128 bits
MAX_DIFFICULTY_BITS = 128 

# The Nonce Field Size (34 Bytes)
MNONCE_FIELD_BYTE_SIZE = 34 
MNONCE_SCALE_FIELD_LOCATION = 0 
MNONCE_LENGTH_FIELD_LOCATION = 1 

MNONCE_DATA_FIELD_BYTE_SIZE = 32
MNONCE_DATA_FIELD_OVERWRITE_SPACING = 2
MNONCE_DATA_FIELD_OVERWRITE_LOCATION = 2 + MNONCE_DATA_FIELD_OVERWRITE_SPACING 
MNONCE_DATA_FIELD_OVERWRITE_SIZE = MNONCE_DATA_FIELD_BYTE_SIZE - MNONCE_DATA_FIELD_OVERWRITE_SPACING 

class SHA3TxPoWController(LiteXModule):
    """
    SHA3 TxPoW Controller (Optimized, Hybrid, Timeout, with DMA support).
    
    FIX: Uses atomic write capture to prevent timing issues where
    the write address increments before the data is consumed.
    """
    def __init__(self):
        # --- CSR Definitions ---
        self._control = CSRStorage(2, description="Control Register [0:Start, 1:Stop]")
        self._status  = CSRStatus(3, description="Status Register [0:Running, 1:Found, 2:Timeout]")
        
        self._nonce_result = CSRStatus(MNONCE_FIELD_BYTE_SIZE * 8, description="Result Nonce")
        self._target = CSRStorage(MAX_DIFFICULTY_BITS, description="Target Difficulty")
        
        self._timeout = CSRStorage(32, description="Timeout Limit (Cycles). 0=Disable")
        
        # Input Length for Padding
        self._input_len = CSRStorage(32, description="Length of input header in bytes")
        
        # Header Data Window
        self._header_data = CSRStorage(WORD_WIDTH, description="Header Data Window")
        
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
        self.submodules.dma = WishboneDMAReader(self.bus, endianness="big", fifo_depth=16, with_csr=True)
        
        # --- Instantiate Miner ---
        self.submodules.miner = KeccakDatapath(
            MAX_BLOCKS=MAX_BLOCKS,
            MAX_DIFFICULTY_BITS=MAX_DIFFICULTY_BITS,
            NONCE_DATA_FIELD_OVERWRITE_LOCATION=MNONCE_DATA_FIELD_OVERWRITE_LOCATION,
            NONCE_DATA_FIELD_OVERWRITE_SIZE=MNONCE_DATA_FIELD_OVERWRITE_SIZE,
            NONCE_FIELD_BYTE_SIZE=MNONCE_FIELD_BYTE_SIZE
        )
        
        # --- Header Storage ---
        # Storage array sized by macro (256 x 64-bit words)
        header_storage = Array(Signal(WORD_WIDTH) for _ in range(HEADER_WORDS))
        
        # --- Header Storage Write Logic (CSR and DMA) ---
        
        # =========================================================================
        # SIMPLE DMA WRITE LOGIC
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
        
        # =========================================================================
        # FIX: 1-Cycle Pipeline Delay
        # =========================================================================
        # The DMA data lags by 1 cycle: when offset=N, data contains word N-2.
        # Solution: Use 1-cycle pipeline registers to align data with address.
        # This naturally compensates for the lag across all transfers.
        
        # Pipeline stage: delay write by 1 cycle
        dma_write_en_d = Signal()
        dma_write_addr_d = Signal(addr_width)
        dma_write_data_d = Signal(WORD_WIDTH)
        
        self.sync += [
            # Capture current cycle's handshake
            dma_write_en_d.eq(self.dma.source.valid & self.dma.source.ready),
            dma_write_addr_d.eq(dma_write_addr),
            dma_write_data_d.eq(self.dma.source.data),
        ]
        
        # Update write address on handshake
        self.sync += [
            If(dma_enable_rising,
                dma_write_addr.eq(0)
            ).Elif(self.dma.source.valid & self.dma.source.ready,
                dma_write_addr.eq(dma_write_addr + 1)
            )
        ]
        
        # Sync: Perform Write (Unrolled for Simulator)
        # Use DELAYED signals - this compensates for the DMA's 1-cycle data lag
        for i in range(HEADER_WORDS):
            self.sync += [
                # Priority 1: DMA write (use delayed/pipelined signals)
                If(dma_write_en_d & (dma_write_addr_d == i),
                    header_storage[i].eq(dma_write_data_d)
                # Priority 2: CSR write (Manual)
                ).Elif(self._header_we.storage & (self._header_addr.storage == i),
                    header_storage[i].eq(self._header_data.storage)
                )
            ]
        
        # =========================================================================
        
        # Connect flattened storage to miner input
        self.comb += self.miner.header_data.eq(Cat(*header_storage))
        
        # --- Control & Status ---
        self.comb += [
            self.miner.target.eq(self._target.storage),
            self.miner.timeout_limit.eq(self._timeout.storage),
            self.miner.input_length.eq(self._input_len.storage), 
            
            self.miner.start.eq(self._control.storage[0]),
            self.miner.stop.eq(self._control.storage[1]),
            
            # Status Mapping
            self._status.status[0].eq(self.miner.running),
            self._status.status[1].eq(self.miner.found != 0),
            self._status.status[2].eq(self.miner.timeout),
            
            # Connect the miner result to the CSR status
            self._nonce_result.status.eq(self.miner.nonce_result)
        ]
        
        # Trigger interrupts
        self.comb += [
            self.ev.found.trigger.eq(self.miner.found != 0),
            self.ev.timeout.trigger.eq(self.miner.timeout)
        ]