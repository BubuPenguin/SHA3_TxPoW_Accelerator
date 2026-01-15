/**
 * SHA3-256 Hardware Accelerator JNI Implementation for Minima
 * 
 * This file provides JNI bindings for the SHA3-256 hardware accelerator
 * to be used from Java (Minima).
 * 
 * Function: jniminingtest(byte[] header, byte[] target) -> byte[] nonce
 * 
 * Compile: See build_jni.sh
 * 
 * Hardware base address: 0xF0000000 (from test_clz_accelerator.c)
 */

#include <jni.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <time.h>

/* --- Hardware Constants (from test_clz_accelerator.c) --- */
#define TXPOW_BASE 0xF0000000
#define REGION_SIZE 4096

/* Register offsets (matching test_clz_accelerator.c) */
#define REG_CONTROL          0x000
#define REG_STATUS           0x004
#define REG_NONCE_RESULT     0x008  // 256-bit (8 words = 32 bytes)
#define REG_HASH_RESULT      0x028  // 256-bit (8 words = 32 bytes)
#define REG_ITERATION_COUNT  0x048  // 64-bit (2 words)
#define REG_TARGET_CLZ       0x050
#define REG_TIMEOUT          0x0E0  // 64-bit (2 words) - Clock cycles
#define REG_INPUT_LEN        0x0E8
#define REG_HEADER_DATA_LOW  0x0EC  // Low 32 bits of 64-bit header word
#define REG_HEADER_DATA_HIGH 0x0F0  // High 32 bits of 64-bit header word
#define REG_HEADER_ADDR      0x0F4  // Word address (0-271 for 2176 bytes)
#define REG_HEADER_WE        0x0F8  // Write enable

/* Status bits */
#define STATUS_IDLE    (1 << 0)
#define STATUS_RUNNING (1 << 1)
#define STATUS_FOUND   (1 << 2)
#define STATUS_TIMEOUT (1 << 3)

/* Control bits */
#define CONTROL_START  (1 << 0)
#define CONTROL_STOP   (1 << 1)

/* Global pointer to memory mapped registers */
static volatile uint32_t *regs = NULL;

/**
 * Initialize Hardware (mmap) - calling this once is efficient
 */
static int init_hw_if_needed(void) {
    if (regs != NULL) return 0; // Already initialized
    
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("[JNI] Failed to open /dev/mem");
        return -1;
    }
    
    // Map 4K page
    regs = (volatile uint32_t *)mmap(NULL, REGION_SIZE, 
                                     PROT_READ | PROT_WRITE, 
                                     MAP_SHARED, fd, TXPOW_BASE);
    close(fd); // fd no longer needed after mmap
    
    if (regs == MAP_FAILED) {
        perror("[JNI] mmap failed");
        regs = NULL;
        return -1;
    }
    
    return 0;
}

/**
 * Convert Target Hash (Bytes) to CLZ (Integer)
 * 
 * Counts leading zero bits in the target byte array.
 * For example: 0x00000FFF... has 12 leading zeros.
 */
static int calculate_clz_from_bytes(const uint8_t *data, int len) {
    int clz = 0;
    for (int i = 0; i < len; i++) {
        uint8_t b = data[i];
        if (b == 0) {
            clz += 8;
        } else {
            // Count leading zeros in this byte
            if ((b & 0xF0) == 0) { clz += 4; b <<= 4; }
            if ((b & 0xC0) == 0) { clz += 2; b <<= 2; }
            if ((b & 0x80) == 0) { clz += 1; }
            break; // Found the first non-zero bit, stop counting
        }
    }
    return clz;
}

/**
 * Write Header Data to FPGA Memory
 * (matching test_clz_accelerator.c write_header_data)
 */
static void write_header_to_fpga(const uint8_t *data, size_t length) {
    // The hardware memory is organized as 272 words (64-bit each)
    // Total capacity is 2176 bytes (16 blocks * 136 bytes)
    size_t num_words = (length + 7) / 8;  // Round up to nearest 8 bytes
    
    for (size_t word_idx = 0; word_idx < num_words; word_idx++) {
        uint64_t word = 0;
        
        // Pack 8 bytes into a 64-bit word
        // This ensures data[0] is at the least significant bits of word 0
        for (int byte_offset = 0; byte_offset < 8; byte_offset++) {
            size_t global_byte_idx = (word_idx * 8) + byte_offset;
            
            if (global_byte_idx < length) {
                // Shift byte into its position within the 64-bit word
                word |= ((uint64_t)data[global_byte_idx]) << (byte_offset * 8);
            }
        }
        
        // Split 64-bit word into two 32-bit registers for the CSR interface
        uint32_t low  = (uint32_t)(word & 0xFFFFFFFF);
        uint32_t high = (uint32_t)(word >> 32);
        
        // Write sequence: Address -> Low Data -> High Data -> Trigger WE
        regs[REG_HEADER_ADDR / 4]      = (uint32_t)word_idx;
        regs[REG_HEADER_DATA_LOW / 4]  = low;
        regs[REG_HEADER_DATA_HIGH / 4] = high;
        
        // Ensure registers are updated before triggering Write Enable
        __sync_synchronize();
        regs[REG_HEADER_WE / 4] = 1;
        
        // Small delay to allow FPGA logic to capture data into memory
        for (volatile int delay = 0; delay < 20; delay++);
        
        regs[REG_HEADER_WE / 4] = 0;
        __sync_synchronize();
    }
}

// ==========================================
// REQUIRED JNI HELPER FUNCTIONS
// (Required by Minima for testing/validation)
// ==========================================

/**
 * Helper: Say Hello
 * Minima calls this to verify the library loaded correctly
 */
JNIEXPORT void JNICALL Java_org_minima_utils_jni_jnifunctions_sayHello
  (JNIEnv *env, jobject obj) {
    printf("[JNI] Hello from SHA3 Accelerator Driver!\n");
}

/**
 * Helper: Sum Integers
 * Minima uses this for validation
 */
JNIEXPORT jlong JNICALL Java_org_minima_utils_jni_jnifunctions_sumIntegers
  (JNIEnv *env, jobject obj, jlong a, jlong b) {
    return a + b;
}

/**
 * Helper: Say Hello To Me
 * Minima uses this for validation
 */
JNIEXPORT jstring JNICALL Java_org_minima_utils_jni_jnifunctions_sayHelloToMe
  (JNIEnv *env, jobject obj, jstring name, jboolean flag) {
    return name; // Return input string
}

// ==========================================
// MINIMA JNI MINING FUNCTIONS
// ==========================================

/**
 * REQUIRED: Single Hash Function
 * 
 * Class:     org_minima_utils_jni_jnifunctions
 * Method:    hashHeader
 * Signature: ([B)[B
 * 
 * Minima calls this to hash data without mining.
 * If your hardware can do a single sha3 hash, map it here.
 * For now, this is a placeholder that returns the input to prevent crashes.
 */
JNIEXPORT jbyteArray JNICALL Java_org_minima_utils_jni_jnifunctions_hashHeader
  (JNIEnv *env, jobject obj, jbyteArray data) {
    
    // TODO: Implement single SHA3 hash using your HW if supported
    // For now, we just return the data so Minima doesn't crash.
    return data;
}

/**
 * REQUIRED: Mining Function
 * 
 * Class:     org_minima_utils_jni_jnifunctions
 * Method:    hashHeaderWithDiff
 * Signature: ([BI[B[B)[B
 * 
 * This connects Minima's mining loop to your Accelerator.
 * 
 * @param env              JNI environment
 * @param obj              Java object (unused for static methods)
 * @param mytestnonce      Input nonce (returned on failure)
 * @param maxattempts      Maximum attempts (can be used for timeout, or ignored)
 * @param targetdifficulty Target difficulty bytes (converted to CLZ internally)
 * @param headerbytes      The TxPoW header bytes (input)
 * @return                 The winning Nonce (32 bytes) or mytestnonce if failed
 */
JNIEXPORT jbyteArray JNICALL Java_org_minima_utils_jni_jnifunctions_hashHeaderWithDiff
  (JNIEnv *env, jobject obj, jbyteArray mytestnonce, jint maxattempts, 
   jbyteArray targetdifficulty, jbyteArray headerbytes) {
    
    // 1. Initialize HW
    if (init_hw_if_needed() < 0) {
        return mytestnonce; // Return input on failure
    }
    
    // 2. Get Input Data
    jsize header_len = (*env)->GetArrayLength(env, headerbytes);
    jsize target_len = (*env)->GetArrayLength(env, targetdifficulty);
    
    if (header_len <= 0 || header_len > 2176) {
        return mytestnonce; // Invalid header length, return input nonce
    }
    
    jbyte *header_data = (*env)->GetByteArrayElements(env, headerbytes, NULL);
    jbyte *target_data = (*env)->GetByteArrayElements(env, targetdifficulty, NULL);
    
    if (header_data == NULL || target_data == NULL) {
        if (header_data) (*env)->ReleaseByteArrayElements(env, headerbytes, header_data, JNI_ABORT);
        if (target_data) (*env)->ReleaseByteArrayElements(env, targetdifficulty, target_data, JNI_ABORT);
        return mytestnonce; // Return input on failure
    }
    
    // 3. Convert Target to CLZ (Minima sends a byte array, we count the zeros)
    int target_clz = calculate_clz_from_bytes((uint8_t*)target_data, target_len);
    
    // Debug print (visible in logcat/console)
    // printf("[JNI] Target CLZ: %d, Input Len: %d, Max Attempts: %d\n", target_clz, header_len, maxattempts);
    
    // 4. Reset & Config Accelerator
    regs[REG_CONTROL / 4] = CONTROL_STOP;
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;
    
    // Write Header to FPGA
    write_header_to_fpga((uint8_t*)header_data, header_len);
    
    // Release input buffers (we have written to FPGA now)
    (*env)->ReleaseByteArrayElements(env, headerbytes, header_data, JNI_ABORT);
    (*env)->ReleaseByteArrayElements(env, targetdifficulty, target_data, JNI_ABORT);
    
    // Set Config
    regs[REG_TARGET_CLZ / 4] = target_clz;
    regs[REG_INPUT_LEN / 4]  = header_len;
    
    // Set Timeout
    // You can use 'maxattempts' here if your HW supports iteration limits,
    // otherwise stick to your HW timeout register.
    regs[REG_TIMEOUT / 4]     = 0; // 0 = Infinite/HW default
    regs[REG_TIMEOUT / 4 + 1] = 0;
    __sync_synchronize();
    
    // 5. Start Mining
    regs[REG_CONTROL / 4] = CONTROL_START;
    __sync_synchronize();
    
    // 6. Poll for Result
    uint32_t status = 0;
    // We can use a simple loop, or check 'maxattempts' to break early if needed
    int sanity_check = 0;
    int found = 0;
    
    while (1) {
        status = regs[REG_STATUS / 4];
        
        if (status & STATUS_FOUND) {
            found = 1;
            break;
        }
        if (status & STATUS_TIMEOUT) {
            break;
        }
        
        // Safety Break (optional, prevents infinite hangs if HW freezes)
        if (sanity_check++ > 10000000) {
            break;
        }
        usleep(10); // Sleep 10us to yield CPU
    }
    
    // 7. Handle Result
    if (found) {
        // Create new byte array for the valid nonce
        jbyteArray result_arr = (*env)->NewByteArray(env, 32);
        if (result_arr == NULL) {
            // Stop HW before returning
            regs[REG_CONTROL / 4] = CONTROL_STOP;
            __sync_synchronize();
            regs[REG_CONTROL / 4] = 0;
            return mytestnonce; // Return input on allocation failure
        }
        
        jbyte nonce_bytes[32];
        
        // Read nonce result (8 words = 32 bytes)
        // LiteX CSRs use big-endian word ordering (MSW first)
        for (int i = 0; i < 8; i++) {
            // Read 32-bit word (in reverse order for LiteX big-endian CSR ordering)
            uint32_t word = regs[(REG_NONCE_RESULT / 4) + (7 - i)];
            
            // Extract bytes (Little Endian inside the word)
            nonce_bytes[i*4 + 0] = (word >> 0) & 0xFF;
            nonce_bytes[i*4 + 1] = (word >> 8) & 0xFF;
            nonce_bytes[i*4 + 2] = (word >> 16) & 0xFF;
            nonce_bytes[i*4 + 3] = (word >> 24) & 0xFF;
        }
        
        (*env)->SetByteArrayRegion(env, result_arr, 0, 32, nonce_bytes);
        
        // Stop HW
        regs[REG_CONTROL / 4] = CONTROL_STOP;
        __sync_synchronize();
        regs[REG_CONTROL / 4] = 0;
        
        return result_arr; // SUCCESS: Return new nonce
    } else {
        // Stop HW
        regs[REG_CONTROL / 4] = CONTROL_STOP;
        __sync_synchronize();
        regs[REG_CONTROL / 4] = 0;
        
        return mytestnonce; // FAILURE: Return original input nonce
    }
}
