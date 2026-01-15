# JNI Integration Guide for SHA3 TxPoW Accelerator

This guide explains how to integrate your SHA3-256 hardware accelerator with Minima using JNI (Java Native Interface).

## Overview

The integration involves:
1. **Java side**: Declare native methods that Minima can call
2. **C JNI wrapper**: Implement native functions that access hardware via `/dev/mem`
3. **Compilation**: Build a shared library (`.so`) that Java can load
4. **Integration**: Connect to Minima's mining code

---

## Step 1: Java Native Interface Declaration

Create a Java class that declares the native methods:

**File: `SHA3AcceleratorJNI.java`**

```java
package com.minima.minima.mining;

/**
 * JNI wrapper for SHA3-256 Hardware Accelerator
 * 
 * Hardware base address: 0xF0000000 (check your LiteX build/csr.csv)
 */
public class SHA3AcceleratorJNI {
    
    // Load the native library
    static {
        try {
            System.loadLibrary("sha3accelerator");
        } catch (UnsatisfiedLinkError e) {
            System.err.println("Failed to load sha3accelerator library: " + e.getMessage());
            System.err.println("Make sure libsha3accelerator.so is in java.library.path");
        }
    }
    
    /**
     * Initialize hardware accelerator
     * Maps /dev/mem to access hardware registers
     * 
     * @return 0 on success, negative on error
     */
    public static native int init();
    
    /**
     * Cleanup and unmap hardware registers
     */
    public static native void cleanup();
    
    /**
     * Write header data to accelerator memory
     * 
     * @param headerData Header bytes (up to 2176 bytes)
     * @param length Actual length in bytes
     * @return 0 on success, negative on error
     */
    public static native int writeHeader(byte[] headerData, int length);
    
    /**
     * Start mining with specified difficulty
     * 
     * @param targetCLZ Target leading zeros (0-256)
     * @param timeoutCycles Timeout in clock cycles (0 = disable)
     * @return 0 on success, negative on error
     */
    public static native int startMining(int targetCLZ, long timeoutCycles);
    
    /**
     * Stop mining (if running)
     */
    public static native void stopMining();
    
    /**
     * Check if a valid nonce was found
     * 
     * @return true if STATUS_FOUND bit is set
     */
    public static native boolean isFound();
    
    /**
     * Check if mining is running
     * 
     * @return true if STATUS_RUNNING bit is set
     */
    public static native boolean isRunning();
    
    /**
     * Get the found nonce (32 bytes: 2-byte spacing + 30-byte nonce)
     * 
     * @return Nonce bytes, or null if not found
     */
    public static native byte[] getNonce();
    
    /**
     * Get the hash result (32 bytes, SHA3-256)
     * 
     * @return Hash bytes, or null if not found
     */
    public static native byte[] getHash();
    
    /**
     * Get iteration count
     * 
     * @return Number of hash iterations performed
     */
    public static native long getIterationCount();
    
    /**
     * Wait for mining to complete (blocking)
     * 
     * @param pollIntervalMs Polling interval in milliseconds
     * @return 0 if found, 1 if timeout, negative on error
     */
    public static native int waitForCompletion(int pollIntervalMs);
}
```

---

## Step 2: Generate JNI Header File

After creating the Java file, generate the JNI header:

```bash
cd /path/to/minima/src
javac -h . com/minima/minima/mining/SHA3AcceleratorJNI.java
```

This generates `com_minima_minima_mining_SHA3AcceleratorJNI.h` with function signatures like:
```c
JNIEXPORT jint JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_init
  (JNIEnv *, jclass);
```

---

## Step 3: C JNI Implementation

**File: `sha3accelerator_jni.c`**

```c
#include <jni.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>

// Hardware base address (update from your LiteX build/csr.csv)
#define SHA3_ACCEL_BASE 0xF0000000
#define REGION_SIZE 4096

// Register offsets (update from your LiteX build/csr.csv)
// These are examples - you MUST get actual offsets from csr.csv after building!
#define REG_CONTROL          0x000
#define REG_STATUS           0x004
#define REG_NONCE_RESULT     0x008  // 256-bit (8 words = 32 bytes)
#define REG_HASH_RESULT      0x028  // 256-bit (8 words = 32 bytes)
#define REG_ITERATION_COUNT  0x048  // 64-bit (2 words)
#define REG_TARGET_CLZ       0x050
#define REG_TIMEOUT          0x0E0  // 64-bit (2 words)
#define REG_INPUT_LEN        0x0E8
#define REG_HEADER_DATA_LOW  0x0EC
#define REG_HEADER_DATA_HIGH 0x0F0
#define REG_HEADER_ADDR      0x0F4
#define REG_HEADER_WE        0x0F8

// Status bits
#define STATUS_IDLE    (1 << 0)
#define STATUS_RUNNING (1 << 1)
#define STATUS_FOUND   (1 << 2)
#define STATUS_TIMEOUT (1 << 3)

// Control bits
#define CONTROL_START  (1 << 0)
#define CONTROL_STOP   (1 << 1)

static volatile uint32_t *regs = NULL;
static int hw_initialized = 0;

/**
 * Initialize hardware accelerator
 */
JNIEXPORT jint JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_init
  (JNIEnv *env, jclass cls) {
    
    if (hw_initialized) {
        return 0; // Already initialized
    }
    
    // Open /dev/mem
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        return -1;
    }
    
    // Map hardware registers
    regs = (volatile uint32_t *)mmap(NULL, REGION_SIZE, 
                                     PROT_READ | PROT_WRITE, 
                                     MAP_SHARED, fd, SHA3_ACCEL_BASE);
    close(fd);
    
    if (regs == MAP_FAILED) {
        regs = NULL;
        return -2;
    }
    
    hw_initialized = 1;
    return 0;
}

/**
 * Cleanup hardware accelerator
 */
JNIEXPORT void JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_cleanup
  (JNIEnv *env, jclass cls) {
    
    if (regs != NULL && regs != MAP_FAILED) {
        munmap((void*)regs, REGION_SIZE);
        regs = NULL;
    }
    hw_initialized = 0;
}

/**
 * Write header data to accelerator
 */
JNIEXPORT jint JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_writeHeader
  (JNIEnv *env, jclass cls, jbyteArray headerData, jint length) {
    
    if (!hw_initialized || regs == NULL) {
        return -1;
    }
    
    if (length <= 0 || length > 2176) {
        return -2; // Invalid length
    }
    
    // Get byte array data
    jbyte *data = (*env)->GetByteArrayElements(env, headerData, NULL);
    if (data == NULL) {
        return -3;
    }
    
    // Calculate number of 64-bit words
    size_t num_words = (length + 7) / 8;
    
    // Write data word by word
    for (size_t word_idx = 0; word_idx < num_words; word_idx++) {
        uint64_t word = 0;
        
        // Pack bytes into 64-bit word (little-endian)
        for (int byte_idx = 0; byte_idx < 8; byte_idx++) {
            size_t global_idx = word_idx * 8 + byte_idx;
            if (global_idx < (size_t)length) {
                word |= ((uint64_t)(uint8_t)data[global_idx]) << (byte_idx * 8);
            }
        }
        
        // Split into two 32-bit values
        uint32_t low  = (uint32_t)(word & 0xFFFFFFFF);
        uint32_t high = (uint32_t)(word >> 32);
        
        // Write to CSR registers
        regs[REG_HEADER_ADDR / 4] = word_idx;
        regs[REG_HEADER_DATA_LOW / 4] = low;
        regs[REG_HEADER_DATA_HIGH / 4] = high;
        __sync_synchronize();
        
        // Trigger write
        regs[REG_HEADER_WE / 4] = 1;
        __sync_synchronize();
        
        // Small delay for hardware to process
        for (volatile int delay = 0; delay < 10; delay++);
        
        // Clear write enable
        regs[REG_HEADER_WE / 4] = 0;
        __sync_synchronize();
    }
    
    // Release byte array
    (*env)->ReleaseByteArrayElements(env, headerData, data, JNI_ABORT);
    
    // Set input length
    regs[REG_INPUT_LEN / 4] = length;
    __sync_synchronize();
    
    return 0;
}

/**
 * Start mining
 */
JNIEXPORT jint JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_startMining
  (JNIEnv *env, jclass cls, jint targetCLZ, jlong timeoutCycles) {
    
    if (!hw_initialized || regs == NULL) {
        return -1;
    }
    
    // Stop any running mining
    regs[REG_CONTROL / 4] = CONTROL_STOP;
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;
    __sync_synchronize();
    
    // Set target difficulty
    regs[REG_TARGET_CLZ / 4] = targetCLZ;
    
    // Set timeout (64-bit register: high word first for LiteX)
    regs[REG_TIMEOUT / 4] = (uint32_t)(timeoutCycles >> 32);
    regs[REG_TIMEOUT / 4 + 1] = (uint32_t)(timeoutCycles & 0xFFFFFFFF);
    __sync_synchronize();
    
    // Start mining
    regs[REG_CONTROL / 4] = CONTROL_START;
    __sync_synchronize();
    
    return 0;
}

/**
 * Stop mining
 */
JNIEXPORT void JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_stopMining
  (JNIEnv *env, jclass cls) {
    
    if (!hw_initialized || regs == NULL) {
        return;
    }
    
    regs[REG_CONTROL / 4] = CONTROL_STOP;
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;
    __sync_synchronize();
}

/**
 * Check if nonce found
 */
JNIEXPORT jboolean JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_isFound
  (JNIEnv *env, jclass cls) {
    
    if (!hw_initialized || regs == NULL) {
        return JNI_FALSE;
    }
    
    uint32_t status = regs[REG_STATUS / 4];
    return (status & STATUS_FOUND) ? JNI_TRUE : JNI_FALSE;
}

/**
 * Check if running
 */
JNIEXPORT jboolean JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_isRunning
  (JNIEnv *env, jclass cls) {
    
    if (!hw_initialized || regs == NULL) {
        return JNI_FALSE;
    }
    
    uint32_t status = regs[REG_STATUS / 4];
    return (status & STATUS_RUNNING) ? JNI_TRUE : JNI_FALSE;
}

/**
 * Get nonce result
 */
JNIEXPORT jbyteArray JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_getNonce
  (JNIEnv *env, jclass cls) {
    
    if (!hw_initialized || regs == NULL) {
        return NULL;
    }
    
    // Check if found
    if (!(regs[REG_STATUS / 4] & STATUS_FOUND)) {
        return NULL;
    }
    
    // Create byte array
    jbyteArray result = (*env)->NewByteArray(env, 32);
    if (result == NULL) {
        return NULL;
    }
    
    jbyte *bytes = (*env)->GetByteArrayElements(env, result, NULL);
    if (bytes == NULL) {
        return NULL;
    }
    
    // Read nonce result (8 words = 32 bytes)
    // LiteX CSRs use big-endian word ordering (MSW first)
    uint32_t nonce_words[8];
    for (int i = 0; i < 8; i++) {
        nonce_words[i] = regs[(REG_NONCE_RESULT / 4) + (7 - i)];
    }
    
    // Extract bytes (little-endian within each word)
    for (int i = 0; i < 8; i++) {
        bytes[i*4 + 0] = (nonce_words[i] >> 0) & 0xFF;
        bytes[i*4 + 1] = (nonce_words[i] >> 8) & 0xFF;
        bytes[i*4 + 2] = (nonce_words[i] >> 16) & 0xFF;
        bytes[i*4 + 3] = (nonce_words[i] >> 24) & 0xFF;
    }
    
    (*env)->ReleaseByteArrayElements(env, result, bytes, 0);
    return result;
}

/**
 * Get hash result
 */
JNIEXPORT jbyteArray JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_getHash
  (JNIEnv *env, jclass cls) {
    
    if (!hw_initialized || regs == NULL) {
        return NULL;
    }
    
    // Check if found
    if (!(regs[REG_STATUS / 4] & STATUS_FOUND)) {
        return NULL;
    }
    
    // Create byte array
    jbyteArray result = (*env)->NewByteArray(env, 32);
    if (result == NULL) {
        return NULL;
    }
    
    jbyte *bytes = (*env)->GetByteArrayElements(env, result, NULL);
    if (bytes == NULL) {
        return NULL;
    }
    
    // Read hash result (8 words = 32 bytes)
    // LiteX CSRs use big-endian word ordering (MSW first)
    uint32_t hash_words[8];
    for (int i = 0; i < 8; i++) {
        hash_words[i] = regs[(REG_HASH_RESULT / 4) + (7 - i)];
    }
    
    // Extract bytes (little-endian within each word)
    for (int i = 0; i < 8; i++) {
        bytes[i*4 + 0] = (hash_words[i] >> 0) & 0xFF;
        bytes[i*4 + 1] = (hash_words[i] >> 8) & 0xFF;
        bytes[i*4 + 2] = (hash_words[i] >> 16) & 0xFF;
        bytes[i*4 + 3] = (hash_words[i] >> 24) & 0xFF;
    }
    
    (*env)->ReleaseByteArrayElements(env, result, bytes, 0);
    return result;
}

/**
 * Get iteration count
 */
JNIEXPORT jlong JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_getIterationCount
  (JNIEnv *env, jclass cls) {
    
    if (!hw_initialized || regs == NULL) {
        return 0;
    }
    
    // Read 64-bit iteration count (LiteX: high word first)
    uint32_t high = regs[REG_ITERATION_COUNT / 4];
    uint32_t low  = regs[(REG_ITERATION_COUNT / 4) + 1];
    uint64_t count = ((uint64_t)high << 32) | low;
    
    return (jlong)count;
}

/**
 * Wait for completion (blocking)
 */
JNIEXPORT jint JNICALL Java_com_minima_minima_mining_SHA3AcceleratorJNI_waitForCompletion
  (JNIEnv *env, jclass cls, jint pollIntervalMs) {
    
    if (!hw_initialized || regs == NULL) {
        return -1;
    }
    
    uint32_t status;
    do {
        status = regs[REG_STATUS / 4];
        
        if (status & STATUS_FOUND) {
            return 0; // Found
        }
        if (status & STATUS_TIMEOUT) {
            return 1; // Timeout
        }
        
        if (pollIntervalMs > 0) {
            usleep(pollIntervalMs * 1000);
        }
    } while (status & STATUS_RUNNING);
    
    return -2; // Stopped without finding
}
```

---

## Step 4: Compile the Native Library

Create a Makefile or build script:

**File: `build_jni.sh`**

```bash
#!/bin/bash

# Get Java home
JAVA_HOME=${JAVA_HOME:-$(dirname $(dirname $(readlink -f $(which javac))))}

if [ ! -d "$JAVA_HOME/include" ]; then
    echo "Error: JAVA_HOME not set or Java includes not found"
    echo "Set JAVA_HOME or ensure javac is in PATH"
    exit 1
fi

echo "Using JAVA_HOME: $JAVA_HOME"

# Compile
gcc -shared -fPIC -O2 \
    -I"$JAVA_HOME/include" \
    -I"$JAVA_HOME/include/linux" \
    -o libsha3accelerator.so \
    sha3accelerator_jni.c

if [ $? -eq 0 ]; then
    echo "Build successful: libsha3accelerator.so"
    echo "Install to system library path or set java.library.path"
else
    echo "Build failed"
    exit 1
fi
```

Make it executable and build:
```bash
chmod +x build_jni.sh
./build_jni.sh
```

---

## Step 5: Get Actual Register Offsets

**IMPORTANT**: You must get the actual register offsets from your LiteX build:

```bash
# After building your LiteX SoC
cat build/alinx_ax7203/csr.csv | grep sha3_txpow
```

Update the `#define` offsets in `sha3accelerator_jni.c` to match your actual hardware.

Also check the base address:
```bash
cat build/alinx_ax7203/csr.csv | grep sha3_txpow | head -1
```

Update `SHA3_ACCEL_BASE` in the C code.

---

## Step 6: Integration with Minima

In Minima's mining code, use the JNI wrapper:

```java
// Initialize hardware
if (SHA3AcceleratorJNI.init() != 0) {
    System.err.println("Failed to initialize hardware accelerator");
    // Fall back to software mining
    return mineSoftware(headerData, targetDifficulty);
}

try {
    // Write header data
    if (SHA3AcceleratorJNI.writeHeader(headerData, headerData.length) != 0) {
        throw new Exception("Failed to write header to hardware");
    }
    
    // Convert difficulty to CLZ (leading zeros)
    int targetCLZ = calculateTargetCLZ(targetDifficulty);
    
    // Start mining (no timeout for now)
    SHA3AcceleratorJNI.startMining(targetCLZ, 0);
    
    // Wait for completion (poll every 100ms)
    int result = SHA3AcceleratorJNI.waitForCompletion(100);
    
    if (result == 0) {
        // Found!
        byte[] nonce = SHA3AcceleratorJNI.getNonce();
        byte[] hash = SHA3AcceleratorJNI.getHash();
        long iterations = SHA3AcceleratorJNI.getIterationCount();
        
        // Extract 30-byte nonce (bytes 2-31 of result)
        byte[] actualNonce = Arrays.copyOfRange(nonce, 2, 32);
        
        return new MiningResult(actualNonce, hash, iterations);
    } else {
        // Timeout or stopped
        return null;
    }
    
} finally {
    SHA3AcceleratorJNI.stopMining();
    SHA3AcceleratorJNI.cleanup();
}
```

---

## Step 7: Deployment

1. **Copy library to system path:**
   ```bash
   sudo cp libsha3accelerator.so /usr/local/lib/
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

---

## Troubleshooting

### Library not found
```bash
# Check library path
java -XshowSettings:properties -version | grep java.library.path

# Verify library exists
ldd libsha3accelerator.so
```

### Permission denied on /dev/mem
```bash
# Run as root (development only)
sudo java -jar minima.jar

# Or configure udev rules for production
```

### Register offsets wrong
- Always get offsets from `build/alinx_ax7203/csr.csv` after building
- Check base address matches your LiteX configuration
- Verify register widths (32-bit vs 64-bit)

### Hardware not responding
- Check hardware is actually in the bitstream
- Verify base address is correct
- Use `test_fixed_iteration.c` to verify hardware works independently

---

## References

- Your C test code: `FixedIterationStop/test_fixed_iteration.c`
- LiteX CSR documentation
- JNI Specification: https://docs.oracle.com/javase/8/docs/technotes/guides/jni/
- Minima JNI directory: https://github.com/minima-global/Minima/tree/dev-pureminima/jni

