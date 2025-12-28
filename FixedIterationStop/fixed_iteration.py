from migen import *
from litex.gen import *

class FixedIterationStop(LiteXModule):
    """
    Test module to force the accelerator to loop for a fixed number of iterations.
    It provides a CLZ of 0 until the iteration count is reached, then triggers.
    """
    def __init__(self, target_iterations=5000000):
        # Inputs
        self.i = Signal(256)           # Connected to raw_hash (ignored)
        self.iteration = Signal(64)    # Connected to miner.iteration_counter
        
        # Output
        self.o = Signal(9)             # CLZ Output
        
        # Logic:
        # If iteration < target, output 0 (Difficulty not met, keep looping)
        # If iteration >= target, output 256 (Difficulty met, STOP)
        self.comb += [
            If(self.iteration >= target_iterations,
                self.o.eq(256)  # Success! Trigger found
            ).Else(
                self.o.eq(0)    # Keep mining...
            )
        ]