# SHA3 TxPoW CLZ-Based Accelerator Hardware Test

This directory contains hardware tests for the SHA3 TxPoW accelerator with CLZ (Count Leading Zeros) based difficulty validation.

## Files

- `test_clz_accelerator.c` - C hardware test program for CLZ-based mining
- `compile_clz.sh` - Compilation script for RISC-V target
- `clz_module.py` - CLZ hardware module (big-endian compatible)
- `clz_test.py` - Python testbench for CLZ module

## Building

```bash
./compile_clz.sh
```

Or manually:
```bash
riscv64-linux-gnu-gcc -o test_clz_accelerator test_clz_accelerator.c -static
```

## Usage

```bash
./test_clz_accelerator [target_clz] [timeout_cycles]
```

### Parameters

- **target_clz**: Number of leading zeros required (difficulty)
  - Range: 0-256
  - Default: 8 (easy difficulty, ~1/256 chance per hash)
  - Typical values:
    - 8 = Easy (very quick)
    - 16 = Medium (~65k hashes on average)
    - 20 = Hard (~1M hashes on average)
    - 24 = Very Hard (~16M hashes on average)

- **timeout_cycles**: Timeout in clock cycles, 0=disabled
  - Default: 0 (no timeout)
  - Example: 10000000 (10M cycles)

### Examples

```bash
# Easy test with 8 leading zeros (quick verification)
./test_clz_accelerator 8

# Medium difficulty, 16 leading zeros
./test_clz_accelerator 16

# Hard difficulty with timeout protection
./test_clz_accelerator 20 10000000
```

## What the Test Does

1. **Initializes Hardware**: Maps the accelerator registers via `/dev/mem`
2. **Generates Test Header**: Creates a 100-byte test header with nonce field structure
3. **Writes Header Data**: Transfers header to accelerator memory
4. **Configures Mining**: Sets target difficulty (CLZ) and timeout
5. **Starts Mining**: Triggers the accelerator
6. **Monitors Progress**: Polls iteration count and status
7. **Validates Results**: 
   - Checks if hash meets difficulty (has enough leading zeros)
   - Verifies nonce consistency across registers
   - Compares hardware CLZ output with software calculation
8. **Reports Results**: Displays timing, hash rate, and verification status

## Output Information

### Status Indicators
- ✓ PASS: Valid nonce found with sufficient difficulty
- ✗ FAIL: Hash doesn't meet difficulty or data inconsistency
- ⚠ TIMEOUT: No valid nonce found within timeout period

### Key Metrics
- **Iteration Count**: Number of hashes computed
- **Hash Rate**: Hashes per second (H/s or MH/s)
- **Cycles per Hash**: Average cycles needed per hash operation
- **CLZ Verification**: Software vs hardware CLZ comparison

### Debug Information
- **Nonce Result**: The winning nonce value (32 bytes)
- **Hash Result**: The SHA3-256 hash output (32 bytes)
- **Block 0 Data**: First 64 bytes showing nonce injection
- **Debug CLZ Registers**: Hardware CLZ values for both SIMD lanes
- **Comparison Flags**: Which hash(es) met the difficulty target

## Register Map

| Register | Offset | Description |
|----------|--------|-------------|
| CONTROL | 0x000 | Start (bit 0), Stop (bit 1) |
| STATUS | 0x004 | Idle, Running, Found, Timeout flags |
| NONCE_RESULT | 0x008 | 256-bit winning nonce |
| HASH_RESULT | 0x028 | 256-bit hash output |
| ITERATION_COUNT | 0x048 | 64-bit iteration counter |
| TARGET_CLZ | 0x050 | Target difficulty (0-256) |
| DEBUG_HASH0 | 0x054 | Debug: Hash from lane 0 |
| DEBUG_HASH1 | 0x074 | Debug: Hash from lane 1 |
| DEBUG_CLZ0 | 0x094 | Debug: CLZ of hash 0 |
| DEBUG_CLZ1 | 0x098 | Debug: CLZ of hash 1 |
| DEBUG_COMPARISON | 0x09C | Debug: Comparison results |
| DEBUG_BLOCK0 | 0x0A0 | Debug: First 64 bytes of block 0 |
| TIMEOUT | 0x0E0 | 64-bit timeout limit |
| INPUT_LEN | 0x0E8 | Input header length |
| HEADER_DATA_LOW | 0x0EC | Header data write (low 32 bits) |
| HEADER_DATA_HIGH | 0x0F0 | Header data write (high 32 bits) |
| HEADER_ADDR | 0x0F4 | Header address for writes |
| HEADER_WE | 0x0F8 | Header write enable |

## Deployment to FPGA

1. **Compile** (on development machine):
   ```bash
   ./compile_clz.sh
   ```

2. **Copy to FPGA**:
   ```bash
   scp test_clz_accelerator root@<fpga_ip>:~/
   ```

3. **Run on FPGA**:
   ```bash
   ssh root@<fpga_ip>
   ./test_clz_accelerator 8
   ```

## Troubleshooting

### "HW Init failed"
- Check that `/dev/mem` is accessible (may need root)
- Verify TXPOW_BASE address matches your hardware

### Test Times Out
- Lower the difficulty (target_clz)
- Increase or disable timeout
- Check that accelerator clock is running

### Hash Doesn't Meet Difficulty
- Check debug CLZ registers vs target
- Verify CLZ module is correctly synthesized
- Check for timing violations in synthesis

### Nonce Mismatch
- Debug register read timing
- Check CSR address offsets match gateware
- Verify LiteX CSR endianness handling

## Comparison with FixedIterationStop Test

The CLZ-based test differs from the fixed iteration test:

| Feature | FixedIterationStop | CLZ-Based |
|---------|-------------------|-----------|
| Stop Condition | Fixed iteration count | Hash meets difficulty |
| Difficulty | None (always succeeds) | Configurable (CLZ) |
| Timeout | Optional | Optional |
| Verification | Iteration count only | Hash difficulty + CLZ |
| Real PoW | No | Yes |

## Next Steps

- **Performance Tuning**: Measure hash rate at different clock frequencies
- **Difficulty Scaling**: Test with progressively higher CLZ values
- **DMA Testing**: Add test for DMA-based header loading
- **Multi-Block**: Test with headers > 136 bytes
- **Endianness Validation**: Verify against reference SHA3 implementation

