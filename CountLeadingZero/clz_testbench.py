import operator
from functools import reduce
from migen import *
from migen.sim import run_simulation

# Import the DUT (Device Under Test)
from clz_module import CountLeadingZeros

# ==============================================================================
# 1. JAVA MIMIC FUNCTION (Verification Reference)
# ==============================================================================

def calculate_java_clz(byte_stream):
    """
    Mimics Java's BigInteger(1, byte_stream).bitLength() logic to find leading zeros.
    
    Java reads the byte_stream as Big Endian.
    - Byte 0 is the Most Significant Byte.
    - Inside Byte 0, Bit 7 is the Most Significant Bit.
    """
    # Convert bytes to a single large integer (Big Endian)
    java_big_int = int.from_bytes(byte_stream, byteorder='big')
    
    # Calculate leading zeros for a 256-bit width
    if java_big_int == 0:
        return 256
    
    # Number of bits actually used
    bit_length = java_big_int.bit_length()
    
    # Leading zeros = Total Width - Used Bits
    return 256 - bit_length

# ==============================================================================
# 2. HARDWARE INPUT CONVERTER
# ==============================================================================

def bytes_to_hw_input(byte_stream):
    """
    Converts the byte stream to the Little Endian integer expected by the hardware.
    
    The hardware expects the FIRST byte of the stream (Java's MSB) 
    to be at the BOTTOM (LSB) of the 256-bit signal because 
    SHA3/Keccak state words are built Little Endian.
    """
    return int.from_bytes(byte_stream, byteorder='little')

# ==============================================================================
# 3. TESTBENCH
# ==============================================================================

def run_clz_test(dut):
    print(f"--- Starting CLZ Simulation (Java Compatibility Mode) ---")
    print(f"{'Test Case':<30} | {'Java View (Big Endian HEX)':<35} | {'Exp':<5} | {'Act':<5} | {'Status'}")
    print("-" * 110)

    # Define Test Vectors (Byte Streams)
    # Each vector represents the 32-byte hash output from the Keccak core
    test_vectors = [
        # Case 1: First byte is 0x80 (1000 0000). Java MSB is 1. CLZ should be 0.
        (b'\x80' + b'\x00'*31, "First Byte 0x80 (MSB set)"),
        
        # Case 2: First byte is 0x01 (0000 0001). Java MSB is 0...01. CLZ should be 7.
        (b'\x01' + b'\x00'*31, "First Byte 0x01 (Bit 0 set)"),
        
        # Case 3: Second byte has the bit. First byte 0x00. CLZ should be 8 + 0 = 8.
        (b'\x00\x80' + b'\x00'*30, "Second Byte 0x80"),
        
        # Case 4: Byte 31 (Last byte) has 1. All others 0. CLZ should be 31*8 + 7 = 255.
        (b'\x00'*31 + b'\x01', "Last Byte 0x01 (Only LSB set)"),
        
        # Case 5: All Zeros. CLZ should be 256.
        (b'\x00'*32, "All Zeros"),
        
        # Case 6: Random Mix - 00 00 0F FF ...
        # First 2 bytes are zero (16 bits)
        # 3rd byte is 0F (0000 1111) -> 4 leading zeros
        # Total = 16 + 4 = 20
        (b'\x00\x00\x0F\xFF' + b'\x00'*28, "Random: 00 00 0F FF ..."),
    ]

    for byte_stream, desc in test_vectors:
        # 1. Calculate Expected (Java Logic)
        expected_clz = calculate_java_clz(byte_stream)
        
        # 2. Prepare Hardware Input (Little Endian Load)
        hw_input_val = bytes_to_hw_input(byte_stream)
        
        # 3. Run Simulation
        yield dut.i.eq(hw_input_val)
        yield # Clock cycle
        actual_clz = (yield dut.o)
        
        # 4. Display
        # Show the first few bytes of the hex string for context
        hex_preview = byte_stream.hex().upper()
        if len(hex_preview) > 20:
            hex_preview = hex_preview[:20] + "..."
            
        status = "✅ PASS" if actual_clz == expected_clz else "❌ FAIL"
        
        print(f"{desc:<30} | 0x{hex_preview:<33} | {expected_clz:<5} | {actual_clz:<5} | {status}")
        
        if actual_clz != expected_clz:
            print(f"   -> DEBUG: HW Input (int): {hw_input_val}")

if __name__ == "__main__":
    dut = CountLeadingZeros(width=256)
    run_simulation(dut, run_clz_test(dut))

