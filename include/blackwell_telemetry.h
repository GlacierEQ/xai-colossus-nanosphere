#ifndef BLACKWELL_TELEMETRY_H
#define BLACKWELL_TELEMETRY_H

#include <string>
#include <stdint.h>
#include <sys/mman.h>

/**
 * APEX Blackwell Telemetry Driver (Ring -3)
 * Optimized for GB200 NVL72 Dual-Die Architecture.
 * 
 * Provides 1ms raw register access to silicon-level metrics.
 */

#define NV_BAR0_SIZE           0x1000000 
#define NV_PTHERM_DIE0_TEMP    0x00020400
#define NV_PTHERM_DIE1_TEMP    0x00020404
#define NV_PPOWER_USAGE_MW     0x00102800

struct BlackwellMetrics {
    float temp_die0;    // Celsius
    float temp_die1;    // Celsius (for dual-die)
    float power_watts;  // Total board power
    uint64_t timestamp; // Epoch nanoseconds
};

class BlackwellTelemetryDriver {
public:
    BlackwellTelemetryDriver(const std::string& pci_address);
    ~BlackwellTelemetryDriver();

    // High-performance polling method (Thread-safe)
    BlackwellMetrics sample();

private:
    int fd;
    uint8_t* bar0;
    std::string pci_addr;

    inline uint32_t read_reg(uint32_t offset) {
        return *(volatile uint32_t*)(bar0 + offset);
    }
};

#endif // BLACKWELL_TELEMETRY_H
