# SHA3 Accelerator JNI Implementation for Minima

Simple JNI wrapper for the SHA3-256 hardware accelerator to enable Java (Minima) access.

## Overview

This implementation provides JNI functions for Minima's `jnifunctions` interface:
- `sayHello()`, `sumIntegers()`, `sayHelloToMe()` - Helper functions for Minima validation
- `hashHeader()` - Single hash function (stub implementation)
- `hashHeaderWithDiff()` - Main mining function that uses the hardware accelerator

## Build Options

### Option 1: Using JNI_minima Build System (Recommended)

The code is compatible with the `JNI_minima` build system structure:

```bash
cd accelerator/txpow_simd/jni/JNI_minima

# Build the library
./buildjni.sh
```

This creates `lib/libnative.so` which implements Minima's `org.minima.utils.jni.jnifunctions` interface.

### Option 2: Using Standalone Build Script

Alternatively, use the standalone build script:

```bash
cd accelerator/txpow_simd/jni

# Make build script executable
chmod +x build_jni.sh

# Build the library
./build_jni.sh
```

This creates `libminima_native.so`.

## Files

- **`sha3accelerator_jni.c`** - C JNI implementation (Minima-compatible interface)
- **`JNI_minima/buildjni.sh`** - Build script for JNI_minima structure
- **`build_jni.sh`** - Standalone build script
- **`JNI_INTEGRATION_GUIDE.md`** - Complete integration guide

## Java Interface

This implementation matches Minima's `jnifunctions.java` interface:

```java
package org.minima.utils.jni;

public class jnifunctions {
    static {
        System.loadLibrary("minima_native"); // loads libminima_native.so
    }
    
    /**
     * Single hash function (stub implementation)
     * 
     * @param data  Data to hash
     * @return      Hash result (currently returns input)
     */
    public static native byte[] hashHeader(byte[] data);
    
    /**
     * Mine for a nonce using hardware accelerator
     * 
     * @param mytestnonce      Input nonce (returned on failure)
     * @param maxattempts      Maximum attempts (can be ignored)
     * @param targetdifficulty Target difficulty bytes (converted to CLZ internally)
     * @param headerbytes      TxPoW header bytes (up to 2176 bytes)
     * @return                 32-byte nonce, or mytestnonce if mining failed/timeout
     */
    public static native byte[] hashHeaderWithDiff(byte[] mytestnonce, int maxattempts, 
                                                    byte[] targetdifficulty, byte[] headerbytes);
}
```

**Important:** The C function names are fixed to match Minima's interface:
- `Java_org_minima_utils_jni_jnifunctions_hashHeader`
- `Java_org_minima_utils_jni_jnifunctions_hashHeaderWithDiff`

## Function Signatures

```c
// Single hash function (stub - returns input for now)
JNIEXPORT jbyteArray JNICALL Java_org_minima_utils_jni_jnifunctions_hashHeader
  (JNIEnv *env, jobject obj, jbyteArray data)

// Mining function
JNIEXPORT jbyteArray JNICALL Java_org_minima_utils_jni_jnifunctions_hashHeaderWithDiff
  (JNIEnv *env, jobject obj, jbyteArray mytestnonce, jint maxattempts,
   jbyteArray targetdifficulty, jbyteArray headerbytes)
```

## Key Features

1. **Target Difficulty Conversion**: Automatically converts target byte array to CLZ (Count Leading Zeros) integer
2. **Memory Management**: Properly releases JNI byte arrays to prevent memory leaks
3. **CPU Yielding**: Uses `usleep(10000)` in polling loop to prevent CPU hogging
4. **Error Handling**: Returns NULL on timeout or hardware failure
5. **Endianness**: Correctly handles LiteX's big-endian CSR word ordering

## Register Offsets

Register offsets match `test_clz_accelerator.c`:
- Base address: `0xF0000000`
- All offsets are defined in the C file (from test_clz_accelerator.c)

If your hardware uses different offsets, update the `#define` values in `sha3accelerator_jni.c`.

## Testing

Test the hardware independently first using:
```bash
cd ../CountLeadingZero
./test_clz_accelerator
```

This verifies the hardware works before integrating with JNI.

## Requirements

- GCC compiler
- Java JDK (for JNI headers)
- Linux system
- Root access or proper permissions for `/dev/mem`

## Deployment

1. **Copy library to system path:**
   ```bash
   sudo cp libminima_native.so /usr/local/lib/
   sudo ldconfig
   ```

2. **Or set java.library.path:**
   ```bash
   java -Djava.library.path=/path/to/library -jar minima.jar
   ```

3. **Ensure permissions:**
   ```bash
   # Allow access to /dev/mem (requires root or proper permissions)
   sudo chmod 666 /dev/mem  # Not recommended for production
   # Better: Add user to appropriate group or use udev rules
   ```

## Notes

- The nonce returned is 32 bytes (full register content)
- Target difficulty is automatically converted from bytes to CLZ integer
- Mining runs until a valid nonce is found or timeout occurs
- The function is blocking - it will not return until mining completes or times out
- **On failure**: Returns `mytestnonce` (input nonce) instead of NULL - Minima expects the input back if nothing was found
- **hashHeader function**: Currently a stub that returns the input. Can be implemented later if hardware supports single-hash mode
