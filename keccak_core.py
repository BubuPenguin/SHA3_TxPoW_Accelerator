#!/usr/bin/env python3

#
# Keccak Core Module
# 
# Pure combinatorial Keccak-f[1600] permutation (one round)
# Similar to keccak_core.sv in the reference implementation
#

from migen import *
from litex.gen import *

from utils import RHO_OFFSETS, rol64

# ====================================================================================================
# Keccak Core - Combinatorial Permutation
# ====================================================================================================

class KeccakCore(LiteXModule):
    """
    Keccak-f[1600] permutation core (one round).
    Similar to keccak_core.sv in the reference implementation.
    
    This is a purely combinatorial implementation that performs all 5 steps in one cycle:
    - Theta (θ): XOR with parity
    - Rho (ρ): Rotate lanes
    - Pi (π): Permute lanes
    - Chi (χ): Non-linear mixing
    - Iota (ι): XOR round constant
    
    Inputs:
        step_input: Array of 25 x 64-bit signals (input state for current step)
        round_const: 64-bit round constant for Iota step (only used in Iota)
        
    Outputs (combinatorial, one per step):
        theta_out: Array of 25 x 64-bit signals (after Theta)
        rho_out: Array of 25 x 64-bit signals (after Rho)
        pi_out: Array of 25 x 64-bit signals (after Pi)
        chi_out: Array of 25 x 64-bit signals (after Chi)
        iota_out: Array of 25 x 64-bit signals (after Iota, final output)
    """
    
    def __init__(self):
        # Input state for current step (25 x 64-bit lanes)
        # This is fed from different sources depending on which step we're on
        self.step_input = Array(Signal(64, name=f"keccak_step_in_{i}") for i in range(25))
        
        # Round constant for Iota step
        self.round_const = Signal(64, name="keccak_round_const")
        
        # Theta step: Compute parity and XOR
        theta_c = Array(Signal(64, name=f"keccak_theta_c_{i}") for i in range(5))
        theta_d = Array(Signal(64, name=f"keccak_theta_d_{i}") for i in range(5))
        
        # C[x] = A[x,0] ^ A[x,1] ^ A[x,2] ^ A[x,3] ^ A[x,4]
        for x in range(5):
            self.comb += theta_c[x].eq(
                self.step_input[x + 0 * 5] ^ self.step_input[x + 1 * 5] ^ 
                self.step_input[x + 2 * 5] ^ self.step_input[x + 3 * 5] ^ self.step_input[x + 4 * 5]
            )
        
        # D[x] = C[x-1] ^ ROL(C[x+1], 1)
        for x in range(5):
            self.comb += theta_d[x].eq(
                theta_c[(x + 4) % 5] ^ rol64(theta_c[(x + 1) % 5], 1)
            )
        
        # Theta output: A'[x,y] = A[x,y] ^ D[x]
        self.theta_out = Array(Signal(64, name=f"keccak_theta_out_{i}") for i in range(25))
        for y in range(5):
            for x in range(5):
                self.comb += self.theta_out[x + 5 * y].eq(
                    self.step_input[x + 5 * y] ^ theta_d[x]
                )
        
        # Rho output: Rotate lanes by fixed offsets
        self.rho_out = Array(Signal(64, name=f"keccak_rho_out_{i}") for i in range(25))
        for y in range(5):
            for x in range(5):
                self.comb += self.rho_out[x + 5 * y].eq(
                    rol64(self.theta_out[x + 5 * y], RHO_OFFSETS[y][x])
                )
        
        # Pi output: Permute lanes A'[Y, (2X+3Y)%5] = A[X,Y]
        self.pi_out = Array(Signal(64, name=f"keccak_pi_out_{i}") for i in range(25))
        for y in range(5):
            for x in range(5):
                dest_x = y
                dest_y = (2 * x + 3 * y) % 5
                src_idx = x + 5 * y
                dest_idx = dest_x + 5 * dest_y
                self.comb += self.pi_out[dest_idx].eq(self.rho_out[src_idx])
        
        # Chi output: Non-linear mixing A'[x,y] = A[x,y] ^ (~A[x+1,y] & A[x+2,y])
        self.chi_out = Array(Signal(64, name=f"keccak_chi_out_{i}") for i in range(25))
        for y in range(5):
            for x in range(5):
                idx = x + 5 * y
                nxt = ((x + 1) % 5) + 5 * y
                nxt2 = ((x + 2) % 5) + 5 * y
                self.comb += self.chi_out[idx].eq(
                    self.pi_out[idx] ^ ((~self.pi_out[nxt]) & self.pi_out[nxt2])
                )
        
        # Iota output: XOR round constant into lane [0,0]
        # All other lanes pass through unchanged
        self.iota_out = Array(Signal(64, name=f"keccak_iota_out_{i}") for i in range(25))
        self.comb += self.iota_out[0].eq(self.chi_out[0] ^ self.round_const)
        for idx in range(1, 25):
            self.comb += self.iota_out[idx].eq(self.chi_out[idx])

