# Java Hardware Test for SHA3-256 Accelerator

This test compares software SHA3-256 (BouncyCastle) with hardware SHA3-256 (FPGA accelerator).

## Prerequisites

1. **Java JDK** (OpenJDK 11 or later)
2. **BouncyCastle library** (`bcprov-jdk18on.jar` or similar)
3. **Native library** (`libnative.so`) - JNI wrapper for hardware accelerator

## Test Data

The test generates a header with the following pattern:
- Bytes 0-1: Nonce structure (scale=1, length=32)
- Bytes 2-33: Nonce field (zeros initially, overwritten at bytes 4-33 when nonce provided)
- Bytes 34+: Repeating pattern `[0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]`

Default input size is 100 bytes, matching the C hardware test default.
Input size can be configured from 1 to 2176 bytes (16 blocks × 136 bytes).

## Build and Run

### Step 1: Download BouncyCastle

```bash
cd accelerator/txpow_simd/VerificationTest/BouncyCastle
wget https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk18on/1.76/bcprov-jdk18on-1.76.jar
```

Or download from: https://www.bouncycastle.org/latest_releases.html

### Step 2: Compile

```bash
./compile.sh
```

This will compile `Java_HW_test.java` and show you how to run the tests.

### Step 3: Run Tests

**Basic test (default 100 bytes, no nonce):**
```bash
./verify_nonce.sh
```

**Test with custom input size:**
```bash
./verify_nonce.sh 200
```

**Verify hardware nonce with specific input size:**
```bash
./verify_nonce.sh <input_size> <30-byte-nonce-in-hex>
```

Examples:
```bash
# 100 bytes with nonce
./verify_nonce.sh 100 a1b2c3d4e5f607182933a4b5c6d7e8f90a1b2c3d4e5f607182933a4b5c6d7e

# 200 bytes with nonce (your example)
./verify_nonce.sh 200 0000005EC244FCABD705DDEBC5F640477D87061E1968787A96E797161CB3C917

# Multi-block test: 544 bytes (4 blocks)
./verify_nonce.sh 544 a1b2c3d4e5f607182933a4b5c6d7e8f90a1b2c3d4e5f607182933a4b5c6d7e
```

### Optional: Native Library for Hardware Access

If you need to implement the JNI wrapper for direct hardware access:

```c
// native.c
#include <jni.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <stdint.h>
#include "Java_HW_test.h"

#define SHA3_ACCEL_BASE 0xF0000000

JNIEXPORT jbyteArray JNICALL Java_Java_1HW_1test_hashData_1Hardware
  (JNIEnv *env, jclass cls, jbyteArray input) {
    
    // TODO: Implement hardware accelerator access via /dev/mem
    // Similar to test_fixed_iteration.c
    
    jbyteArray result = (*env)->NewByteArray(env, 32);
    // ... hardware hash computation ...
    return result;
}
```

Compile native library:
```bash
gcc -shared -fPIC -I${JAVA_HOME}/include -I${JAVA_HOME}/include/linux \
    -o libnative.so native.c
```

The `verify_nonce.sh` script will automatically load `libnative.so` if it exists.

## Expected Output

### Basic Test (No Nonce)

```bash
./verify_nonce.sh
```

```
========================================
SHA3-256 Hash Comparison Test
========================================
Using base header (no nonce inserted)

Base Header Data:
Input data length: 136 bytes
  [0000] 01 20 00 00 00 00 00 00  00 00 00 00 00 00 00 00  |. ..............|
  [0010] 00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  |................|
  [0020] 00 00 33 44 55 66 77 88  11 22 33 44 55 66 77 88  |..3DUfw.."3DUfw.|
  ...

--- SOFTWARE HASH (BouncyCastle) ---
Software Hash (Hex): 0x<hash_value>

========================================
Software-only test completed successfully
========================================
```

### Verifying Hardware Result (With Nonce)

When the hardware accelerator finds a valid nonce, you can verify it:

```bash
# Example: Insert a 30-byte nonce into the test data
./verify_nonce.sh 0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e
```

```
========================================
SHA3-256 Hash Comparison Test
========================================
Nonce provided via command line
Parsed nonce: 30 bytes
Inserting 30-byte nonce into header...

Modified Header Data (with nonce):
Input data length: 136 bytes
  [0000] 01 20 00 00 01 02 03 04  05 06 07 08 09 0a 0b 0c  |. ..............|
  [0010] 0d 0e 0f 10 11 12 13 14  15 16 17 18 19 1a 1b 1c  |................|
  [0020] 1d 1e 33 44 55 66 77 88  11 22 33 44 55 66 77 88  |..3DUfw.."3DUfw.|
  ...

--- SOFTWARE HASH (BouncyCastle) ---
Software Hash (Hex): 0x<computed_hash>
```

## Notes

- The native library (`libnative.so`) is currently not implemented
- Without hardware, the test will show a `UnsatisfiedLinkError` for the hardware path
- The software hash will still be computed and displayed for verification
- Once the native library is implemented, both software and hardware hashes can be compared

## Verifying Hardware Accelerator Results

### Step 1: Get Nonce from Hardware

When the C test completes, it displays the nonce result:

```
Nonce Result Register (32 bytes):
  Structure: {30-byte nonce, 2-byte spacing from header}
  Bytes 0-1 - Header spacing (bytes [2:3]):  00 00 (not overwritten)
  Bytes 2-31 - Nonce data (30 bytes, header bytes [4:33]):
    a1 b2 c3 d4 e5 f6 07 18 29 3a 4b 5c 6d 7e
    8f 90 a1 b2 c3 d4 e5 f6 07 18 29 3a 4b 5c 6d 7e
```

Extract the **30-byte nonce** (bytes 2-31 of the register).

### Step 2: Verify with Java

Run the Java test with the extracted nonce:

```bash
./verify_nonce.sh a1b2c3d4e5f607182933a4b5c6d7e8f90a1b2c3d4e5f607182933a4b5c6d7e
```

The software hash should match the hardware hash result!

### Nonce Structure

The nonce insertion follows the hardware accelerator logic:

**Full Header (136 bytes):**
- **Byte 0**: Scale field (NOT overwritten) = 0x01
- **Byte 1**: Length field (NOT overwritten) = 0x20 (32)
- **Bytes 2-3**: Spacing (NOT overwritten) = 0x00 0x00
- **Bytes 4-33**: 30-byte nonce (OVERWRITTEN during mining)
- **Bytes 34-135**: Remaining header data

**Nonce Result Register (32 bytes):**
- **Bytes 0-1**: Spacing from header bytes [2:3]
- **Bytes 2-31**: 30-byte nonce value

## Matching C Test

This Java test uses identical input data to `test_fixed_iteration.c`, allowing you to verify that:
1. Both tests hash the same input
2. Software SHA3 matches expected results
3. Hardware accelerator produces correct output
4. Hardware nonce can be verified by inserting it into the Java test

