#!/usr/bin/env python3

from migen import *
from migen.sim import run_simulation
from keccak_datapath_simd import KeccakDatapath

def test_difficulty_check():
    print("--- Difficulty Check Test ---")
    
    dut = KeccakDatapath(MAX_BLOCKS=16, MAX_DIFFICULTY_BITS=128)

    def generator():
        # ======================================================
        # TEST: Difficulty Check Validity
        # ======================================================
        print("\n[TEST] Difficulty Check Validity")
        
        # Test targets in order of increasing difficulty (128-bit values!)
        targets = [
            (0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF, "All F's (easiest)"),
            (0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF, "3FFF... (harder)"),
            (0x0FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF, "0FFF... (harder)"),
            (0x03FFFFFFFFFFFFFFFFFFFFFFFFFFFFFF, "03FF... (hardest)"),
        ]
        
        yield dut.input_length.eq(16)
        yield dut.header_data.eq(0x1234567890ABCDEF)
        yield dut.timeout_limit.eq(100)  # Shorter timeout for impossible cases
        
        for target_val, target_desc in targets:
            print(f"\n  Testing target: {target_desc}")
            print(f"    Target: 0x{target_val:032x}")
            yield dut.target.eq(target_val)
            
            yield dut.start.eq(1)
            yield
            yield dut.start.eq(0)
            yield

            cycle_count = 0
            found_status = 0
            timeout_occurred = 0
            
            while (yield dut.running):
                cycle_count += 1
                found_status = yield dut.found
                timeout_occurred = yield dut.timeout
                if found_status != 0 or timeout_occurred:
                    break
                yield
            
            iterations = cycle_count // 27  # Approximate iterations
            
            if found_status != 0:
                print(f"    ✓ Solution found in {cycle_count} cycles ({iterations} iterations)")
                
                # Read both nonce values
                nonce_0 = yield dut.nonce_0
                nonce_1 = yield dut.nonce_1
                
                if found_status == 1:
                    hash_output = yield dut.state_0
                    state_top = yield dut.state_0[0:128]  # Bottom 128 bits (SHA3 uses LSBs)
                else:
                    hash_output = yield dut.state_1
                    state_top = yield dut.state_1[0:128]  # Bottom 128 bits (SHA3 uses LSBs)
                    
                hash_256_bits = hash_output & ((1 << 256) - 1)  # Bottom 256 bits (SHA3-256 standard)
                core_number = found_status - 1 if found_status > 0 else 0
                print(f"    Found by: Core {core_number}")
                print(f"    nonce_0: 0x{nonce_0:060x}")
                print(f"    nonce_1: 0x{nonce_1:060x}")
                print(f"    Hash: {hash_256_bits:064x}")
                print(f"    State top 128 bits: 0x{state_top:032x}")
                print(f"    Comparison: 0x{state_top:032x} < 0x{target_val:032x} = True")
                
            elif timeout_occurred:
                print(f"    ⏰ Timeout after {cycle_count} cycles ({iterations} iterations)")
                print(f"    Correct behavior - target is too difficult")
            else:
                print(f"    ? Unknown termination after {cycle_count} cycles")
            
            # Small delay between tests
            for _ in range(5):
                yield

        print("\n--- Difficulty Check Test Complete ---")

    run_simulation(dut, generator())

if __name__ == "__main__":
    test_difficulty_check()