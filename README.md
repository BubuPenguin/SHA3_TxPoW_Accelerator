# Keccak/SHA3-256 SIMD Mining Accelerator

A hardware accelerator implementation for Keccak/SHA3-256 proof-of-work mining using SIMD (Single Instruction, Multiple Data) architecture with hybrid linear and stochastic nonce search strategies.

## Features

- **SIMD Architecture**: Dual-core parallel processing (Core 0: Linear search, Core 1: Stochastic chain)
- **Keccak-f[1600] Permutation**: Full hardware implementation of the Keccak permutation
- **SHA3-256 Hashing**: Complete SHA3-256 hash computation with proper padding
- **Multi-block Support**: Handles input messages spanning multiple 136-byte blocks
- **Nonce Injection**: Configurable nonce field injection for mining operations
- **Difficulty Checking**: Hardware-accelerated difficulty target comparison

## Architecture

### Components

- **`keccak_datapath_simd.py`**: Main datapath with SIMD dual-core architecture
- **`keccak_core.py`**: Keccak-f[1600] permutation core
- **`sha3_txpow_controller.py`**: Top-level controller with CSR interface
- **`sha3_function.py`**: Software reference implementation for validation
- **`utils.py`**: Shared utilities and constants

### Mining Strategy

- **Core 0**: Linear search - increments nonce sequentially (nonce_0++)
- **Core 1**: Stochastic chain - uses hash output as next nonce (nonce_1 = state_1[0:240])

## Testbenches

Located in `Testbenches/`:
- `test_sha3_validity.py`: Hash validity verification
- `test_nonce_injection.py`: Nonce injection and padding verification
- `test_difficulty_check.py`: Difficulty target checking
- `test_multiblock_processing.py`: Multi-block message processing
- `debug_multiblock.py`: Multi-block debugging utilities

## Requirements

- Python 3.x
- Migen (Python-based hardware description language)
- LiteX (SoC builder framework)

## Usage

See individual testbench files for usage examples.

## License

[Add your license here]

