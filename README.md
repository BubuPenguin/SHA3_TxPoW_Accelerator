# Keccak/SHA3-256 SIMD Mining Accelerator

A hardware accelerator implementation for Keccak/SHA3-256 proof-of-work mining using SIMD (Single Instruction, Multiple Data) architecture with hybrid linear and stochastic nonce search strategies.

## Features

- **SIMD Architecture**: Dual-core parallel processing (Core 0: Linear nonce increment, Core 1: Stochastic nonce chain)
- **Keccak-f[1600] Permutation**: Full 24-round hardware implementation of the Keccak-f[1600] state permutation
- **SHA3-256 Hashing**: Complete SHA3-256 hash computation with Keccak padding (0x06 suffix byte)
- **Multi-block Support**: Handles input messages up to 4 blocks (544 bytes) with proper rate-based absorption
- **Nonce Injection**: 30-byte nonce field injection at fixed byte positions (bytes 4-33) during hash computation
- **Difficulty Checking**: Hardware-accelerated leading zero counting with bit-reversal for Java BigInteger compatibility

## Architecture

### Components

- **`keccak_datapath_simd.py`**: Main datapath with SIMD dual-core architecture
- **`keccak_core.py`**: Keccak-f[1600] permutation core
- **`sha3_txpow_controller.py`**: Top-level controller with CSR interface
- **`utils.py`**: Shared utilities and constants
- **`CountLeadingZero/clz_module.py`**: Hardware implementation of leading zero counter for difficulty checking
  - Implements bit-reversal on output hash to match Java BigInteger behavior
  - Uses binary search/priority encoder for efficient 256-bit leading zero counting
  - Validates hash outputs against difficulty targets
  - `clz_testbench.py`: Migen simulation testbench
  - `test_clz_accelerator.c`: FPGA hardware test with memory-mapped register access

### Mining Strategy

- **Core 0**: Linear search - increments nonce sequentially (nonce_0++)
- **Core 1**: Stochastic chain - uses hash output as next nonce (nonce_1 = state_1[0:240])

## Testbenches

Located in `Testbenches/`:
- **`test_sha3_validity.py`**: Core hash validity verification
  - Verifies SHA3-256 hash correctness against software reference
  - Tests basic datapath functionality
- **`test_nonce_injection.py`**: Nonce injection and padding verification
  - Tests nonce XOR injection into data stream
  - Verifies SHA3 padding location and correctness
- **`test_multiblock_processing.py`**: Multi-block message processing
  - Tests handling of multi-block inputs (up to 544 bytes)
  - Verifies difficulty comparison using MSBs (bits 128-255)
  - Tests both linear and stochastic search paths
- **`test_sha3_txpow_controller_csr.py`**: Top-level controller test with CSR interface
  - Tests mining controller with CSR-based data loading
  - Verifies full mining flow and result readback
- **`test_sha3_txpow_controller_dma.py`**: Top-level controller test with DMA interface
  - Tests mining controller with Wishbone DMA data loading
  - Simulates RAM block and DMA transfers

## Verification Tests

Located in `VerificationTest/`:
- **`sha3_function.py`**: Software reference implementation for SHA3-256 validation
  - Little-endian byte ordering matching hardware implementation
  - Used by testbenches for hash verification
- **`BouncyCastle/`**: Java-based cross-platform verification
  - Uses BouncyCastle library for independent SHA3-256 implementation
  - `Java_HW_test.java`: Verifies hardware accelerator output against Java BigInteger behavior
  - Validates nonce injection and hash computation match between hardware and software
  - Can verify hardware-generated nonces by inserting them into test data
  - Provides platform-independent validation (Java vs Python vs Hardware)
  
## Benchmarks

### Accelerator Tests (`accelerator_hashtest/`)
Performance benchmarks running directly on the hardware accelerator.
- **`hashtest_attempts.c`**: Measures hashrate across varying attempt limits (10 to 100M).
- **`hashtest_inputsize.c`**: Benchmarks hashrate versus input payload size (up to 4 blocks).
- **`hashtest_pulse.c`**: Runs short 1-second pulses to measuring peak burst performance.

### CPU Baseline (`cpu_hashtest/`)
Software-only benchmarks for performance comparison.
- **`sha3_bench_sw.c`**: Optimized C implementation measuring software Keccak hashrate on the CPU.
- **`Sha3Bench.java`**: Java-based benchmark using BouncyCastle (simulates Minima node performance).

## Integration

### JNI Bridge (`jni/`) (Work In Progress)
Native interface for integrating the accelerator with the Minima Java node.
- **`sha3accelerator_jni.c`**: C-side JNI implementation (Currently Incomplete/Experimental).
- **`JNI_INTEGRATION_GUIDE.md`**: Guide for building and linking the shared library.


## Requirements

- Python 3.x
- Migen (Python-based hardware description language)
- LiteX (SoC builder framework)

## Debug & Development Tools

### Debug Modules

- **`FixedIterationStop/fixed_iteration.py`**: Controlled iteration testing module
  - Forces accelerator to run for a fixed number of iterations before triggering success
  - Outputs CLZ=0 (not met) until target iterations reached, then CLZ=256 (success)
  - Useful for performance profiling and verification without random difficulty dependencies

### Not Implemented

- **`WishboneDMA/`**: LiteX Wishbone DMA exploration tests (not implemented in accelerator)
  - `test_pure_dma.py`: Synchronous DMA reader test with fixed 1-to-1 data transfer
  - `test_dma_characteristic.py`: Minimal test exploring LiteX DMA timing characteristics
  - Early experiments for potential DMA-based data transfer (currently uses CSR interface)

