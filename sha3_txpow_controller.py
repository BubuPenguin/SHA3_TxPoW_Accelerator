from migen import *
from litex.gen import *
from litex.soc.interconnect.csr import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourcePulse
from migen.genlib.misc import log2_int

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
MNONCE_FIELD_BYTE_SIZE = 34 #data[0:33] MiniNumber has max size of 32 bytes + 2 bytes for scale and length
MNONCE_SCALE_FIELD_LOCATION = 0 #data[0]
MNONCE_LENGTH_FIELD_LOCATION = 1 #data[1]

MNONCE_DATA_FIELD_BYTE_SIZE = 32
MNONCE_DATA_FIELD_OVERWRITE_SPACING = 2
MNONCE_DATA_FIELD_OVERWRITE_LOCATION = 2 + MNONCE_DATA_FIELD_OVERWRITE_SPACING #data[4]
MNONCE_DATA_FIELD_OVERWRITE_SIZE = MNONCE_DATA_FIELD_BYTE_SIZE - MNONCE_DATA_FIELD_OVERWRITE_SPACING #data[4:33]

class SHA3TxPoWController(LiteXModule):
    """
    SHA3 TxPoW Controller (Optimized, Hybrid, Timeout).
    
    CSR Map:
    - control (RW): [0:Start, 1:Stop]
    - status (RO):  [0:Running, 1:Found, 2:Timeout]
    - nonce_result (RO): Found Nonce (Size: MNONCE_FIELD_BYTE_SIZE * 8)
    - target (RW): Target Difficulty (Size: MAX_DIFFICULTY_BITS)
    - timeout (RW): 32-bit Timeout Limit (in cycles). 0 = Disable.
    
    - input_len (RW): Length of the input header in bytes.
    - header (Windowed RW): [data, addr, we] - Stores raw header data
    """
    def __init__(self):
        # --- CSR Definitions ---
        self._control = CSRStorage(2, description="Control Register [0:Start, 1:Stop]")
        self._status  = CSRStatus(3, description="Status Register [0:Running, 1:Found, 2:Timeout]")
        
        # Updated to use Macros (converting Bytes to Bits)
        self._nonce_result = CSRStatus(MNONCE_FIELD_BYTE_SIZE * 8, description="Result Nonce")
        self._target = CSRStorage(MAX_DIFFICULTY_BITS, description="Target Difficulty")
        
        self._timeout = CSRStorage(32, description="Timeout Limit (Cycles). 0=Disable")
        
        # Input Length for Padding
        self._input_len = CSRStorage(32, description="Length of input header in bytes")
        
        # Header Data Window
        # Uses 64-bit word width
        self._header_data = CSRStorage(WORD_WIDTH, description="Header Data Window")
        
        # Dynamic address width calculation
        # 2048 bytes / 8 bytes per word = 256 words. log2(256) = 8 bits.
        addr_width = log2_int(HEADER_WORDS, need_pow2=False)
        self._header_addr = CSRStorage(addr_width, description=f"Header Address (0-{HEADER_WORDS-1})") 
        
        self._header_we   = CSRStorage(1, description="Header Write Enable")
        
        # Interrupts (Found OR Timeout)
        self.submodules.ev = EventManager()
        self.ev.found   = EventSourcePulse(description="Valid Nonce Found")
        self.ev.timeout = EventSourcePulse(description="Mining Timed Out")
        self.ev.finalize()
        
        # --- Instantiate Miner ---
        # PASSING MACROS TO MINER
        self.submodules.miner = KeccakDatapath(
            MAX_BLOCKS=MAX_BLOCKS,
            TARGET_BITS=MAX_DIFFICULTY_BITS,
            NONCE_START_BYTE=MNONCE_DATA_FIELD_OVERWRITE_LOCATION,
            NONCE_WIDTH_BYTES=MNONCE_DATA_FIELD_OVERWRITE_SIZE # Explicitly passing width
        )
        
        # --- Header Storage ---
        # Storage array sized by macro (256 x 64-bit words)
        header_storage = Array(Signal(WORD_WIDTH) for _ in range(HEADER_WORDS))
        
        self.sync += [
            If(self._header_we.storage,
                header_storage[self._header_addr.storage].eq(self._header_data.storage)
            )
        ]
        
        # Connect flattened storage to miner input
        # Note: Cat() creates a signal where index 0 is LSB. 
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