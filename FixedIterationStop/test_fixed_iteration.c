#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <time.h>

#define TXPOW_BASE 0xF0000000

/* Register Offsets */
#define REG_CONTROL          0x000
#define REG_STATUS           0x004
#define REG_NONCE_RESULT     0x008  // 256-bit result (8 words = 32 bytes)
#define REG_HASH_RESULT      0x028  // 256-bit result (8 words = 32 bytes)
#define REG_ITERATION_COUNT  0x048  // 64-bit status (2 words)
#define REG_TARGET_CLZ       0x050  
#define REG_TIMEOUT          0x0E0  // 64-bit register (2 words)
#define REG_INPUT_LEN        0x0E8
#define REG_HEADER_DATA_LOW  0x0EC  // Low 32 bits of 64-bit header word
#define REG_HEADER_DATA_HIGH 0x0F0  // High 32 bits of 64-bit header word
#define REG_HEADER_ADDR      0x0F4  // Word address (0-271 for 2176 bytes)
#define REG_HEADER_WE        0x0F8  // Write enable
// NOTE: Update this offset from csr.json after rebuilding gateware!
#define REG_DEBUG_BLOCK0     0x0A0  // Debug: First 64 bytes of block 0 (16 words = 64 bytes)

#define STATUS_IDLE    (1 << 0)
#define STATUS_RUNNING (1 << 1)
#define STATUS_FOUND   (1 << 2)

static volatile uint32_t *regs = NULL;

// Read CPU cycle counter (RISC-V)
static inline uint64_t read_cycles(void) {
    uint64_t cycles;
    asm volatile ("rdcycle %0" : "=r" (cycles));
    return cycles;
}

int init_hw(void) {
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) return -1;
    regs = (volatile uint32_t *)mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, fd, TXPOW_BASE);
    return (regs == MAP_FAILED) ? -1 : 0;
}

void write_header_data(const uint8_t *data, size_t length) {
    printf("Writing %zu bytes of header data...\n", length);
    
    // Calculate number of 64-bit words needed
    size_t num_words = (length + 7) / 8;  // Round up to nearest 8 bytes
    
    for (size_t word_idx = 0; word_idx < num_words; word_idx++) {
        uint64_t word = 0;
        
        // Pack up to 8 bytes into a 64-bit word (little-endian)
        for (int byte_idx = 0; byte_idx < 8; byte_idx++) {
            size_t global_idx = word_idx * 8 + byte_idx;
            if (global_idx < length) {
                word |= ((uint64_t)data[global_idx]) << (byte_idx * 8);
            }
        }
        
        // Split 64-bit word into two 32-bit values (little-endian)
        uint32_t low  = (uint32_t)(word & 0xFFFFFFFF);
        uint32_t high = (uint32_t)(word >> 32);
        
        // Write to CSR registers
        regs[REG_HEADER_ADDR / 4] = word_idx;
        regs[REG_HEADER_DATA_LOW / 4] = low;
        regs[REG_HEADER_DATA_HIGH / 4] = high;
        regs[REG_HEADER_WE / 4] = 1;  // Trigger write
        __sync_synchronize();
        
        // CRITICAL: Need to wait for hardware to process the write
        // The CSR write is combinational, but the memory write happens on clock edge
        // Add a small delay to ensure write completes
        for (volatile int delay = 0; delay < 10; delay++);
        
        regs[REG_HEADER_WE / 4] = 0;  // Clear write enable
        __sync_synchronize();
    }
    
    printf("Header data written successfully.\n");
}

void generate_test_header(uint8_t *buffer, size_t length) {
    // Repeating pattern (same as Python testbench)
    uint8_t pattern[] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};
    
    // Fill with repeating pattern
    for (size_t i = 0; i < length; i++) {
        buffer[i] = pattern[i % 8];
    }
    
    // Set nonce field structure (bytes 0-33)
    buffer[0] = 1;   // Scale field
    buffer[1] = 32;  // Length field
    
    // Nonce data field (bytes 2-33) - initialize to zero
    for (int i = 2; i < 34; i++) {
        buffer[i] = 0;
    }
}

void display_header_data(const uint8_t *data, size_t length) {
    printf("\nInput Header Data (%zu bytes):\n", length);
    
    // Display in rows of 16 bytes
    for (size_t i = 0; i < length; i += 16) {
        printf("  [%04zx] ", i);
        
        // Print hex values
        for (size_t j = 0; j < 16 && (i + j) < length; j++) {
            printf("%02x ", data[i + j]);
            if (j == 7) printf(" ");  // Extra space in middle
        }
        
        // Padding if last row is incomplete
        for (size_t j = length - i; j < 16; j++) {
            printf("   ");
            if (j == 7) printf(" ");
        }
        
        // Print ASCII representation
        printf(" |");
        for (size_t j = 0; j < 16 && (i + j) < length; j++) {
            uint8_t c = data[i + j];
            printf("%c", (c >= 32 && c < 127) ? c : '.');
        }
        printf("|\n");
    }
}

void run_iteration_test() {
    printf("--- Starting Fixed Iteration Hardware Test ---\n");

    /* 1. Reset and Clear State */
    regs[REG_CONTROL / 4] = 2; // Stop bit
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;
    
    /* 2. Generate and write test header data */
    uint8_t header_data[100];  // Reduced from 136 to 100 bytes
    generate_test_header(header_data, sizeof(header_data));
    display_header_data(header_data, sizeof(header_data));
    write_header_data(header_data, sizeof(header_data));
    
    /* 3. Setup Configuration */
    // Note: target_clz must be > 0 because the FixedIterationStop 
    // module returns 0 until the iteration target is hit. 
    // If target_clz is 0, the FSM will trigger instantly at iteration 0.
    regs[REG_TARGET_CLZ / 4] = 64; 
    regs[REG_INPUT_LEN / 4]  = 100; // Changed from 136 to 100 bytes
    // Disable timeout (64-bit register, write both words)
    regs[REG_TIMEOUT / 4]     = 0;  // High word
    regs[REG_TIMEOUT / 4 + 1] = 0;  // Low word
    __sync_synchronize();

    /* 4. Start Accelerator */
    printf("Triggering Accelerator Start...\n");
    
    uint64_t start_cycles = read_cycles();
    struct timespec start_time, end_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);
    
    regs[REG_CONTROL / 4] = 1; // Start bit
    __sync_synchronize();

    /* 5. Monitor Loop */
    uint64_t last_iters = 0;
    while (!(regs[REG_STATUS / 4] & STATUS_FOUND)) {
        // Read 64-bit iteration counter (LiteX CSR: big-endian, HIGH word first)
        uint32_t high = regs[(REG_ITERATION_COUNT / 4)];
        uint32_t low  = regs[(REG_ITERATION_COUNT / 4) + 1];
        uint64_t current_iters = ((uint64_t)high << 32) | low;

        if (current_iters >= last_iters + 100000) {
            printf("Progress: %llu iterations...\n", (unsigned long long)current_iters);
            last_iters = current_iters;
        }
        usleep(50000); // Poll every 50ms
    }

    uint64_t end_cycles = read_cycles();
    clock_gettime(CLOCK_MONOTONIC, &end_time);
    
    uint64_t total_cycles = end_cycles - start_cycles;
    double elapsed = (end_time.tv_sec - start_time.tv_sec) + 
                     (end_time.tv_nsec - start_time.tv_nsec) / 1e9;

    /* 6. Final Report */
    uint32_t final_high = regs[(REG_ITERATION_COUNT / 4)];
    uint32_t final_low  = regs[(REG_ITERATION_COUNT / 4) + 1];
    uint64_t final_iters = ((uint64_t)final_high << 32) | final_low;

    // Read nonce result (32 bytes = 8 words)
    // NOTE: LiteX CSRs use BIG-ENDIAN word ordering (MSW first)
    uint32_t nonce[8];
    for (int i = 0; i < 8; i++) {
        // Read in reverse order to handle LiteX's big-endian CSR word ordering
        nonce[i] = regs[(REG_NONCE_RESULT / 4) + (7 - i)];
    }

    // Read hash result (32 bytes = 8 words)
    uint32_t hash[8];
    for (int i = 0; i < 8; i++) {
        // Read in reverse order to handle LiteX's big-endian CSR word ordering
        hash[i] = regs[(REG_HASH_RESULT / 4) + (7 - i)];
    }
    
    // Read debug block data (first 64 bytes with nonce injected, 16 words)
    // NOTE: LiteX CSRs use BIG-ENDIAN word ordering (MSW first)
    // For a 16-word CSR: CSR[0] = Word[15], CSR[1] = Word[14], ..., CSR[15] = Word[0]
    uint32_t debug_block[16];
    uint8_t debug_bytes[64];
    for (int i = 0; i < 16; i++) {
        // Read in reverse order to handle LiteX's big-endian CSR word ordering
        debug_block[i] = regs[(REG_DEBUG_BLOCK0 / 4) + (15 - i)];
    }
    
    // Extract bytes from debug block (little-endian within each word)
    for (int i = 0; i < 16; i++) {
        debug_bytes[i*4 + 0] = (debug_block[i] >> 0) & 0xFF;
        debug_bytes[i*4 + 1] = (debug_block[i] >> 8) & 0xFF;
        debug_bytes[i*4 + 2] = (debug_block[i] >> 16) & 0xFF;
        debug_bytes[i*4 + 3] = (debug_block[i] >> 24) & 0xFF;
    }
    
    // Extract nonce bytes from the result
    uint8_t nonce_bytes[32];
    for (int i = 0; i < 8; i++) {
        nonce_bytes[i*4 + 0] = (nonce[i] >> 0) & 0xFF;
        nonce_bytes[i*4 + 1] = (nonce[i] >> 8) & 0xFF;
        nonce_bytes[i*4 + 2] = (nonce[i] >> 16) & 0xFF;
        nonce_bytes[i*4 + 3] = (nonce[i] >> 24) & 0xFF;
    }

    printf("\n--- Test Complete ---\n");
    printf("Status Register: 0x%08X\n", regs[REG_STATUS / 4]);
    printf("Final Iteration Count: %llu\n", (unsigned long long)final_iters);
    printf("\nTiming Results:\n");
    printf("  Wall-clock time:    %.4f seconds\n", elapsed);
    printf("  Total CPU cycles:   %llu\n", (unsigned long long)total_cycles);
    printf("  Cycles per hash:    %.2f\n", (double)total_cycles / final_iters);
    printf("  Hash rate:          %.2f H/s\n", (double)final_iters / elapsed);
    printf("  Hash rate:          %.6f MH/s\n", ((double)final_iters / elapsed) / 1e6);
    
    printf("\nNonce Result Register (32 bytes):\n");
    printf("  Structure: {30-byte nonce, 2-byte spacing from header}\n");
    printf("  Bytes 0-1 - Header spacing (bytes [2:3]):  %02x %02x (not overwritten)\n", 
           nonce_bytes[0], nonce_bytes[1]);
    printf("  Bytes 2-31 - Nonce data (30 bytes, header bytes [4:33]):\n    ");
    for (int i = 2; i < 32; i++) {
        printf("%02x ", nonce_bytes[i]);
        if (i == 15) printf("\n    ");  // Line break after 14 bytes
    }
    printf("\n");
    printf("  Note: Full header structure is [scale][length][spacing][nonce]\n");
    printf("        Register contains only [spacing][nonce] (32 bytes)\n");
    
    printf("\nNonce Result (32 bytes, raw words):\n  ");
    for (int i = 0; i < 8; i++) {
        printf("%08x ", nonce[i]);
        if (i == 3) printf("\n  ");
    }
    printf("\n");
    
    printf("\nHash Result (32 bytes, raw words):\n  ");
    for (int i = 0; i < 8; i++) {
        printf("%08x ", hash[i]);
        if (i == 3) printf("\n  ");
    }
    printf("\n");
    
    // Extract hash bytes (little-endian from words)
    uint8_t hash_bytes[32];
    for (int i = 0; i < 8; i++) {
        hash_bytes[i*4 + 0] = (hash[i] >> 0) & 0xFF;
        hash_bytes[i*4 + 1] = (hash[i] >> 8) & 0xFF;
        hash_bytes[i*4 + 2] = (hash[i] >> 16) & 0xFF;
        hash_bytes[i*4 + 3] = (hash[i] >> 24) & 0xFF;
    }
    
    printf("\nHash Result (32 bytes, as byte array):\n  0x");
    for (int i = 0; i < 32; i++) {
        printf("%02X", hash_bytes[i]);
    }
    printf("\n");
    
    printf("\n=== DEBUG: FIRST 64 BYTES OF BLOCK 0 (WITH NONCE INJECTED) ===\n");
    printf("This shows the actual data being hashed after nonce insertion\n\n");
    
    // Display in hex dump format (16 bytes per line)
    for (int i = 0; i < 64; i += 16) {
        printf("  [0x%04x] ", i);
        
        // Hex values
        for (int j = 0; j < 16; j++) {
            if (i + j < 64) {
                printf("%02x ", debug_bytes[i + j]);
            } else {
                printf("   ");
            }
            if (j == 7) printf(" ");
        }
        
        // ASCII representation
        printf(" |");
        for (int j = 0; j < 16; j++) {
            if (i + j < 64) {
                uint8_t c = debug_bytes[i + j];
                printf("%c", (c >= 32 && c < 127) ? c : '.');
            }
        }
        printf("|\n");
    }
    
    printf("\nNote: This debug data shows:\n");
    printf("  Bytes 0-1:   Scale (0x%02x) and Length (0x%02x) fields\n", 
           debug_bytes[0], debug_bytes[1]);
    printf("  Bytes 2-3:   Spacing (0x%02x 0x%02x, not overwritten)\n",
           debug_bytes[2], debug_bytes[3]);
    printf("  Bytes 4-33:  30-byte nonce (overwritten by hardware)\n");
    printf("  Bytes 34-63: Header data continuation\n");
    
    // Verify nonce consistency
    printf("\n--- NONCE VERIFICATION ---\n");
    printf("Comparing nonce_result register (bytes 2-31) with debug_block (bytes 4-33):\n");
    int nonce_match = 1;
    for (int i = 0; i < 30; i++) {
        if (nonce_bytes[i + 2] != debug_bytes[i + 4]) {
            nonce_match = 0;
            printf("  [MISMATCH at byte %d] nonce_result[%d]=0x%02x vs debug_block[%d]=0x%02x\n",
                   i, i+2, nonce_bytes[i+2], i+4, debug_bytes[i+4]);
        }
    }
    if (nonce_match) {
        printf("  ✓ MATCH: Nonce data is consistent between registers\n");
        printf("  30-byte nonce value: ");
        for (int i = 0; i < 30; i++) {
            printf("%02x", nonce_bytes[i + 2]);
            if ((i + 1) % 15 == 0 && i < 29) printf("\n                       ");
        }
        printf("\n");
    }
    printf("===============================================================\n");

    if (final_iters > 0) {
        printf("\nRESULT: PASS - Accelerator successfully looped.\n");
    } else {
        printf("\nRESULT: FAIL - Accelerator triggered prematurely.\n");
    }

    // Stop to clear found bit
    regs[REG_CONTROL / 4] = 0;
}

int main() {
    if (init_hw() < 0) {
        perror("HW Init failed");
        return 1;
    }
    run_iteration_test();
    return 0;
}