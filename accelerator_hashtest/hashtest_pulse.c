/**
 * SHA3 TxPoW CLZ Accelerator - Pulse Scaling Test
 * 
 * Benchmarks Hashrate vs Input Payload Size using fixed 1-second pulses.
 * Input scaling: 100, 200, 350, 450, 600, 750, 850, 1000 bytes.
 * 10 Repetitions per size.
 * 
 * Compile: ./compile_hashtest_pulse.sh
 * Run: ./hashtest_pulse
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
#define PULSE_CYCLES 100000000ULL // 1 Second at 100MHz
#define REPETITIONS  10           // Repetitions per input size
#define MAX_INPUT_SIZE 2176
#define BENCHMARK_OUTPUT "hashtest_pulse_results.csv"

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

int calc_blocks(int input_size) {
    return (input_size + 135) / 136;
}

// Struct to hold single run stats
typedef struct {
    double time_sec;
    uint64_t hashes;
} PulseResult;

PulseResult run_single_pulse(int input_size) {
    PulseResult res = {0};
    
    // 1. Reset
    regs[REG_CONTROL / 4] = 2;
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;

    // 2. Configure
    regs[REG_TARGET_CLZ / 4] = 255;
    regs[REG_INPUT_LEN / 4]  = input_size;
    regs[REG_TIMEOUT / 4]     = (uint32_t)(PULSE_CYCLES >> 32);
    regs[REG_TIMEOUT / 4 + 1] = (uint32_t)(PULSE_CYCLES & 0xFFFFFFFF);
    regs[REG_ATTEMPT_LIMIT / 4]     = 0; // Unlimited
    regs[REG_ATTEMPT_LIMIT / 4 + 1] = 0;
    
    __sync_synchronize();

    // 3. Run
    struct timespec start_time, end_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);
    
    regs[REG_CONTROL / 4] = 1;
    __sync_synchronize();

    // 4. Wait
    struct timespec wait_start, wait_current;
    clock_gettime(CLOCK_MONOTONIC, &wait_start);
    
    while (1) {
        uint32_t status = regs[REG_STATUS / 4];
        if ((status & STATUS_TIMEOUT) || (status & STATUS_FOUND)) break;
        
        // Safety timeout (3s)
        clock_gettime(CLOCK_MONOTONIC, &wait_current);
        double elapsed = (wait_current.tv_sec - wait_start.tv_sec) + 
                         (wait_current.tv_nsec - wait_start.tv_nsec) / 1e9;
        if (elapsed > 3.0) {
            printf(" [WARN: Software Timeout] ");
            regs[REG_CONTROL / 4] = 2; 
            break;
        }
        usleep(1000);
    }
    
    clock_gettime(CLOCK_MONOTONIC, &end_time);
    res.time_sec = (end_time.tv_sec - start_time.tv_sec) + 
                   (end_time.tv_nsec - start_time.tv_nsec) / 1e9;

    // 5. Read hashes
    uint32_t h = regs[(REG_ITERATION_COUNT / 4)];
    uint32_t l  = regs[(REG_ITERATION_COUNT / 4) + 1];
    res.hashes = ((uint64_t)h << 32) | l;
    
    // Stop
    regs[REG_CONTROL / 4] = 0;
    
    return res;
}

int main(int argc, char *argv[]) {
    if (init_hw() < 0) {
        perror("HW Init failed");
        return 1;
    }

    printf("=== CLZ Accelerator Pulse Scaling Test ===\n");
    printf("Pulse: %llu cycles (1.0s @ 100MHz)\n", (unsigned long long)PULSE_CYCLES);
    printf("Reps:  %d per size\n", REPETITIONS);
    printf("Output: %s\n", BENCHMARK_OUTPUT);
    printf("----------------------------------------------------------------------\n");
    printf("%-5s %-7s %-12s %-12s %-12s\n", "Size", "Blocks", "Avg MH/s", "Avg Cyc/Hash", "Avg Hashes");
    
    FILE *fp = fopen(BENCHMARK_OUTPUT, "w");
    if (!fp) {
        perror("Failed to open output csv");
        return 1;
    }
    fprintf(fp, "Attempts,Input Size,Blocks,AvgCpuCycles,AvgTime (s),AvgHashRate (MH/s),AvgCyclesPerHash\n");

    int sizes[] = {100, 200, 350, 450, 600, 750, 850, 1024};
    int num_sizes = sizeof(sizes) / sizeof(sizes[0]);

    // Pre-allocate header buffer
    uint8_t header_buffer[MAX_INPUT_SIZE];

    for (int i = 0; i < num_sizes; i++) {
        int sz = sizes[i];
        
        // Setup header data once for this size
        generate_test_header(header_buffer, sz);
        write_header_data(header_buffer, sz);
        
        double sum_mhs = 0;
        double sum_cyc_hash = 0;
        double sum_time = 0;
        uint64_t sum_hashes = 0;
        
        for (int r = 0; r < REPETITIONS; r++) {
            PulseResult res = run_single_pulse(sz);
            
            double mhs = (res.hashes / res.time_sec) / 1e6;
            double cyc_hash = (res.hashes > 0) ? ((double)PULSE_CYCLES / res.hashes) : 0;
            
            sum_hashes += res.hashes;
            sum_time += res.time_sec;
            sum_mhs += mhs;
            sum_cyc_hash += cyc_hash;
            
            // Progress dot
            // printf("."); fflush(stdout);
        }
        
        double avg_hashes = (double)sum_hashes / REPETITIONS;
        double avg_time = sum_time / REPETITIONS;
        double avg_mhs = sum_mhs / REPETITIONS;
        double avg_cyc_hash = sum_cyc_hash / REPETITIONS;
        
        printf("%-5d %-7d %-12.4f %-12.2f %-12.0f\n", 
               sz, calc_blocks(sz), avg_mhs, avg_cyc_hash, avg_hashes);
               
        // "Attempts" column in pulse test is AvgHashes (since time is fixed)
        // We calculate AvgCpuCycles as Total Pulse Cycles (it runs for full duration unless interrupted)
        // BUT wait, cycles/hash = PulseCycles / hashes. So total cycles = PulseCycles.
        // However, user asked for AvgCpuCycles.
        
        fprintf(fp, "%.2f,%d,%d,%.0f,%.6f,%.4f,%.2f\n",
                avg_hashes,
                sz, 
                calc_blocks(sz), 
                (double)PULSE_CYCLES, // Fixed 100M cycles
                avg_time, 
                avg_mhs, 
                avg_cyc_hash);
        fflush(fp);
    }

    fclose(fp);
    printf("----------------------------------------------------------------------\n");
    printf("Done.\n");

    return 0;
}
