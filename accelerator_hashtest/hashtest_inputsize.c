/**
 * SHA3 TxPoW CLZ Accelerator - Input Size Scaling Test
 * 
 * Benchmarks Hashrate vs Input Payload Size.
 * Test Variant: Fixed Attempts (10 Million), No Time Limit.
 * 
 * Compile: ./compile_hashtest_inputsize.sh
 * Run: ./hashtest_inputsize
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

/* Configuration */
#define ATTEMPT_LIMIT 10000000ULL // 10 Million
#define MAX_INPUT_SIZE 2176
#define BENCHMARK_OUTPUT "hashtest_inputsize_results.csv"

/* Register Offsets */
#define REG_CONTROL          0x000
#define REG_STATUS           0x004
#define REG_ITERATION_COUNT  0x048
#define REG_TARGET_CLZ       0x050
#define REG_TIMEOUT          0x0E0
#define REG_ATTEMPT_LIMIT    0x0E8
#define REG_INPUT_LEN        0x0F0
#define REG_HEADER_DATA_LOW  0x0F4
#define REG_HEADER_DATA_HIGH 0x0F8
#define REG_HEADER_ADDR      0x0FC
#define REG_HEADER_WE        0x100

#define STATUS_IDLE    (1 << 0)
#define STATUS_RUNNING (1 << 1)
#define STATUS_FOUND   (1 << 2)
#define STATUS_TIMEOUT (1 << 3)

static volatile uint32_t *regs = NULL;

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
    size_t num_words = (length + 7) / 8;
    for (size_t word_idx = 0; word_idx < num_words; word_idx++) {
        uint64_t word = 0;
        for (int byte_offset = 0; byte_offset < 8; byte_offset++) {
            size_t global_byte_idx = (word_idx * 8) + byte_offset;
            if (global_byte_idx < length) {
                word |= ((uint64_t)data[global_byte_idx]) << (byte_offset * 8);
            }
        }
        
        uint32_t low  = (uint32_t)(word & 0xFFFFFFFF);
        uint32_t high = (uint32_t)(word >> 32);
        
        regs[REG_HEADER_ADDR / 4]      = (uint32_t)word_idx;
        regs[REG_HEADER_DATA_LOW / 4]  = low;
        regs[REG_HEADER_DATA_HIGH / 4] = high;
        
        __sync_synchronize();
        regs[REG_HEADER_WE / 4] = 1;
        for (volatile int delay = 0; delay < 20; delay++);
        regs[REG_HEADER_WE / 4] = 0;
        __sync_synchronize();
    }
}

void generate_test_header(uint8_t *buffer, size_t length) {
    uint8_t pattern[] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00, 0x11};
    for (size_t i = 0; i < length; i++) {
        buffer[i] = pattern[i % 8];
    }
    buffer[0] = 1; // Scale
    buffer[1] = 32; // Length
    for (int i = 2; i < 34; i++) buffer[i] = 0; // Clear Nonce
}

// Calculate blocks 
// Block size is 136 bytes (1088 bits rate)
int calc_blocks(int input_size) {
    return (input_size + 135) / 136;
}

void run_test_for_size(int input_size, FILE *fp) {
    printf("Testing Input Size: %d bytes (%d blocks)... ", input_size, calc_blocks(input_size));
    fflush(stdout);

    // 1. Reset
    regs[REG_CONTROL / 4] = 2;
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;
    
    // 2. Setup Data
    uint8_t header_data[MAX_INPUT_SIZE];
    generate_test_header(header_data, input_size);
    write_header_data(header_data, input_size);

    // 3. Configure
    regs[REG_TARGET_CLZ / 4] = 255;
    regs[REG_INPUT_LEN / 4]  = input_size;
    regs[REG_TIMEOUT / 4]     = 0;
    regs[REG_TIMEOUT / 4 + 1] = 0;
    
    regs[REG_ATTEMPT_LIMIT / 4]     = (uint32_t)(ATTEMPT_LIMIT >> 32);
    regs[REG_ATTEMPT_LIMIT / 4 + 1] = (uint32_t)(ATTEMPT_LIMIT & 0xFFFFFFFF);
    
    __sync_synchronize();


    // 4. Run
    uint64_t start_cycles = read_cycles();
    struct timespec start_time, end_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);
    
    regs[REG_CONTROL / 4] = 1;
    __sync_synchronize();

    // 5. Wait
    struct timespec wait_start, wait_current;
    clock_gettime(CLOCK_MONOTONIC, &wait_start);
    
    while (1) {
        uint32_t status = regs[REG_STATUS / 4];
        
        if ((status & STATUS_FOUND) || (status & STATUS_TIMEOUT) || !(status & STATUS_RUNNING)) {
            break; 
        }
        
        // Safety timeout (200s for 10M attempts)
        clock_gettime(CLOCK_MONOTONIC, &wait_current);
        double elapsed = (wait_current.tv_sec - wait_start.tv_sec) + 
                         (wait_current.tv_nsec - wait_start.tv_nsec) / 1e9;
        if (elapsed > 200.0) {
            printf("[TIMEOUT] ");
            break;
        }
        
        usleep(1000);
    }
    
    uint64_t cycles = read_cycles() - start_cycles;
    
    clock_gettime(CLOCK_MONOTONIC, &end_time);
    double total_time = (end_time.tv_sec - start_time.tv_sec) + 
                        (end_time.tv_nsec - start_time.tv_nsec) / 1e9;

    // 6. Results
    uint32_t h = regs[(REG_ITERATION_COUNT / 4)];
    uint32_t l  = regs[(REG_ITERATION_COUNT / 4) + 1];
    uint64_t hashes = ((uint64_t)h << 32) | l;
    
    // Reset control
    regs[REG_CONTROL / 4] = 0;

    double mh_s = 0;
    if (total_time > 0) {
        mh_s = (hashes / total_time) / 1e6;
    }

    double cyc_per_hash = (hashes > 0) ? (cycles / (double)hashes) : 0;

    printf("Done. %.2f MH/s\n", mh_s);
    
    if (fp) {
        fprintf(fp, "%llu,%d,%d,%llu,%.6f,%.4f,%.2f\n", 
                (unsigned long long)ATTEMPT_LIMIT, 
                input_size, 
                calc_blocks(input_size), 
                (unsigned long long)cycles,
                total_time, 
                mh_s,
                cyc_per_hash);
        fflush(fp);
    }
}

int main() {
    if (init_hw() < 0) {
        perror("HW Init failed");
        return 1;
    }

    printf("=== CLZ Accelerator Input Scaling Test (Fixed Attempts) ===\n");
    printf("Attempts: %llu per test\n", (unsigned long long)ATTEMPT_LIMIT);
    printf("Output:   %s\n", BENCHMARK_OUTPUT);
    printf("----------------------------------------\n");

    FILE *fp = fopen(BENCHMARK_OUTPUT, "w");
    if (!fp) {
        perror("Failed to open output file");
        return 1;
    }
    fprintf(fp, "Attempts,Input Size,Blocks,AvgCpuCycles,AvgTime (s),AvgHashRate (MH/s),AvgCyclesPerHash\n");
    
    // Define Test Points
    int sizes[] = {100, 200, 350, 450, 600, 750, 850, 1024};
    int num_tests = sizeof(sizes) / sizeof(sizes[0]);
    
    for (int i = 0; i < num_tests; i++) {
        run_test_for_size(sizes[i], fp);
    }
    
    fclose(fp);
    printf("----------------------------------------\n");
    printf("Benchmark Complete.\n");

    return 0;
}
