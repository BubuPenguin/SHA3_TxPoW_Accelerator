/**
 * SHA3 TxPoW CLZ Accelerator - FPGA Hardware Test
 * 
 * This test runs on the RISC-V SoC and communicates with the FPGA accelerator
 * via memory-mapped registers at 0xF0000000.
 * 
 * Compile: ./compile_clz.sh
 * Run on hardware: ./test_clz_accelerator [target_clz] [timeout_cycles]
 */

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
#define REG_DEBUG_HASH0      0x054  // 256-bit (8 words)
#define REG_DEBUG_HASH1      0x074  // 256-bit (8 words)
#define REG_DEBUG_CLZ0       0x094  
#define REG_DEBUG_CLZ1       0x098  
#define REG_DEBUG_COMPARISON 0x09C  
#define REG_DEBUG_BLOCK0     0x0A0  // Debug: First 64 bytes of block 0 (16 words = 64 bytes)
#define REG_TIMEOUT          0x0E0  // 64-bit register (2 words) - Clock cycles
#define REG_INPUT_LEN        0x0E8
#define REG_HEADER_DATA_LOW  0x0EC  // Low 32 bits of 64-bit header word
#define REG_HEADER_DATA_HIGH 0x0F0  // High 32 bits of 64-bit header word
#define REG_HEADER_ADDR      0x0F4  // Word address (0-271 for 2176 bytes)
#define REG_HEADER_WE        0x0F8  // Write enable

#define STATUS_IDLE    (1 << 0)
#define STATUS_RUNNING (1 << 1)
#define STATUS_FOUND   (1 << 2)
#define STATUS_TIMEOUT (1 << 3)

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
        
        // Wait for hardware to process the write
        for (volatile int delay = 0; delay < 10; delay++);
        
        regs[REG_HEADER_WE / 4] = 0;  // Clear write enable
        __sync_synchronize();
    }
    
    printf("Header data written successfully.\n");
}

void generate_test_header(uint8_t *buffer, size_t length) {
    // Repeating pattern
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
    printf("Input Header: %zu bytes (nonce field at bytes 0-33)\n", length);
}

void run_clz_test(int target_clz, uint64_t timeout_cycles) {
    printf("\n=== CLZ Mining Test ===\n");
    printf("Target: %d leading zeros | Timeout: %s\n", 
           target_clz,
           timeout_cycles == 0 ? "disabled" : "enabled");

    /* 1. Reset */
    regs[REG_CONTROL / 4] = 2; // Stop
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;
    
    /* 2. Setup header */
    uint8_t header_data[100];
    generate_test_header(header_data, sizeof(header_data));
    display_header_data(header_data, sizeof(header_data));
    write_header_data(header_data, sizeof(header_data));
    
    /* 3. Configure */
    regs[REG_TARGET_CLZ / 4] = target_clz;
    regs[REG_INPUT_LEN / 4]  = 100;
    regs[REG_TIMEOUT / 4]     = (uint32_t)(timeout_cycles >> 32);
    regs[REG_TIMEOUT / 4 + 1] = (uint32_t)(timeout_cycles & 0xFFFFFFFF);
    __sync_synchronize();

    /* 4. Start */
    printf("Starting mining...\n");
    
    uint64_t start_cycles = read_cycles();
    struct timespec start_time, end_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);
    
    regs[REG_CONTROL / 4] = 1;
    __sync_synchronize();

    /* 5. Monitor */
    uint64_t last_iters = 0;
    uint32_t status = 0;
    while (1) {
        status = regs[REG_STATUS / 4];
        
        if (status & STATUS_FOUND) {
            printf("\n✓ Solution found!\n");
            break;
        }
        
        if (status & STATUS_TIMEOUT) {
            printf("\n✗ Timeout!\n");
            break;
        }
        
        uint32_t high = regs[(REG_ITERATION_COUNT / 4)];
        uint32_t low  = regs[(REG_ITERATION_COUNT / 4) + 1];
        uint64_t current_iters = ((uint64_t)high << 32) | low;

        if (current_iters >= last_iters + 100000) {
            printf("  %llu iterations...\n", (unsigned long long)current_iters);
            last_iters = current_iters;
        }
        usleep(50000);
    }

    uint64_t end_cycles = read_cycles();
    clock_gettime(CLOCK_MONOTONIC, &end_time);
    
    uint64_t total_cycles = end_cycles - start_cycles;
    double elapsed = (end_time.tv_sec - start_time.tv_sec) + 
                     (end_time.tv_nsec - start_time.tv_nsec) / 1e9;

    /* 6. Read results */
    uint32_t final_high = regs[(REG_ITERATION_COUNT / 4)];
    uint32_t final_low  = regs[(REG_ITERATION_COUNT / 4) + 1];
    uint64_t final_iters = ((uint64_t)final_high << 32) | final_low;

    uint32_t nonce[8];
    for (int i = 0; i < 8; i++) {
        nonce[i] = regs[(REG_NONCE_RESULT / 4) + (7 - i)];
    }

    uint32_t hash[8];
    for (int i = 0; i < 8; i++) {
        hash[i] = regs[(REG_HASH_RESULT / 4) + (7 - i)];
    }
    
    uint32_t debug_clz0 = regs[REG_DEBUG_CLZ0 / 4];
    uint32_t debug_clz1 = regs[REG_DEBUG_CLZ1 / 4];
    uint32_t debug_comparison = regs[REG_DEBUG_COMPARISON / 4];
    
    uint8_t hash_bytes[32];
    for (int i = 0; i < 8; i++) {
        hash_bytes[i*4 + 0] = (hash[i] >> 0) & 0xFF;
        hash_bytes[i*4 + 1] = (hash[i] >> 8) & 0xFF;
        hash_bytes[i*4 + 2] = (hash[i] >> 16) & 0xFF;
        hash_bytes[i*4 + 3] = (hash[i] >> 24) & 0xFF;
    }
    
    uint8_t nonce_bytes[32];
    for (int i = 0; i < 8; i++) {
        nonce_bytes[i*4 + 0] = (nonce[i] >> 0) & 0xFF;
        nonce_bytes[i*4 + 1] = (nonce[i] >> 8) & 0xFF;
        nonce_bytes[i*4 + 2] = (nonce[i] >> 16) & 0xFF;
        nonce_bytes[i*4 + 3] = (nonce[i] >> 24) & 0xFF;
    }

    /* 7. Report */
    printf("\n=== Results ===\n");
    printf("Iterations: %llu\n", (unsigned long long)final_iters);
    printf("Time:       %.4f sec\n", elapsed);
    printf("Hash rate:  %.2f MH/s\n", ((double)final_iters / elapsed) / 1e6);
    
    if (status & STATUS_FOUND) {
        // Determine which lane won
        int lane0_winner = (debug_comparison & 0x01) != 0;
        int lane1_winner = (debug_comparison & 0x02) != 0;
        
        // Extract the 30-byte nonce data (bytes 2-31 of nonce_result)
        // The nonce_result contains [2-byte spacing][30-byte nonce]
        uint8_t winning_nonce_30bytes[30];
        for (int i = 0; i < 30; i++) {
            winning_nonce_30bytes[i] = nonce_bytes[i + 2];
        }
        
        // Convert to 64-bit integer for calculation
        // Note: Only using lower bytes for the increment calculation
        uint64_t winning_nonce_val = 0;
        for (int i = 0; i < 8 && i < 30; i++) {
            winning_nonce_val |= ((uint64_t)winning_nonce_30bytes[i]) << (i * 8);
        }
        
        // Calculate both nonce values
        // In SIMD: lane 0 tests even values (N), lane 1 tests odd values (N+1)
        uint8_t nonce0_bytes[30];
        uint8_t nonce1_bytes[30];
        
        if (lane0_winner) {
            // Lane 0 won, so winning nonce is nonce0
            memcpy(nonce0_bytes, winning_nonce_30bytes, 30);
            // nonce1 = nonce0 + 1
            uint64_t nonce1_val = winning_nonce_val + 1;
            for (int i = 0; i < 30; i++) {
                nonce1_bytes[i] = (i < 8) ? ((nonce1_val >> (i * 8)) & 0xFF) : 0;
            }
        } else {
            // Lane 1 won, so winning nonce is nonce1
            memcpy(nonce1_bytes, winning_nonce_30bytes, 30);
            // nonce0 = nonce1 - 1
            uint64_t nonce0_val = winning_nonce_val - 1;
            for (int i = 0; i < 30; i++) {
                nonce0_bytes[i] = (i < 8) ? ((nonce0_val >> (i * 8)) & 0xFF) : 0;
            }
        }
        
        printf("\n--- Nonces Tested (SIMD) ---\n");
        printf("Nonce 0 (Lane 0): 0x");
        for (int i = 0; i < 30; i++) {
            printf("%02X", nonce0_bytes[i]);
        }
        printf(" [CLZ=%u%s]\n", debug_clz0, lane0_winner ? " ✓" : "");
        
        printf("Nonce 1 (Lane 1): 0x");
        for (int i = 0; i < 30; i++) {
            printf("%02X", nonce1_bytes[i]);
        }
        printf(" [CLZ=%u%s]\n", debug_clz1, lane1_winner ? " ✓" : "");
        
        printf("\n--- Hash Output ---\n");
        printf("0x");
        for (int i = 0; i < 32; i++) {
            printf("%02X", hash_bytes[i]);
        }
        printf("\n");
        
        printf("\n--- Leading Zeros ---\n");
        printf("Target:     %d\n", target_clz);
        printf("Hash 0 CLZ: %u %s\n", debug_clz0, 
               lane0_winner ? "(winner)" : "");
        printf("Hash 1 CLZ: %u %s\n", debug_clz1,
               lane1_winner ? "(winner)" : "");
        
        // Determine winner CLZ
        int winner_clz = lane0_winner ? debug_clz0 : debug_clz1;
        
        if (winner_clz >= target_clz) {
            printf("\n✓✓✓ PASS ✓✓✓\n");
            printf("Valid nonce found (%d leading zeros)\n", winner_clz);
        } else {
            printf("\n✗✗✗ FAIL ✗✗✗\n");
            printf("Hardware error: reported success but CLZ=%d < target=%d\n", 
                   winner_clz, target_clz);
        }
    } else if (status & STATUS_TIMEOUT) {
        printf("\n⚠ TIMEOUT ⚠\n");
        printf("No solution found in %llu iterations\n", (unsigned long long)final_iters);
    }

    // Stop
    regs[REG_CONTROL / 4] = 2;
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;
}

int main(int argc, char *argv[]) {
    if (init_hw() < 0) {
        perror("HW Init failed");
        return 1;
    }
    
    int target_clz = 8;
    uint64_t timeout = 0;  // 0 = disabled (no clock cycle limit)
    
    if (argc >= 2) {
        target_clz = atoi(argv[1]);
    }
    if (argc >= 3) {
        timeout = strtoull(argv[2], NULL, 10);
    }
    
    printf("SHA3 TxPoW CLZ Accelerator Test\n");
    printf("Usage: %s [target_clz] [timeout_cycles]\n", argv[0]);
    printf("  timeout_cycles: Hardware clock cycles (not iterations)\n");
    
    run_clz_test(target_clz, timeout);
    
    return 0;
}

