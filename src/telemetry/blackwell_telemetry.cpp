#include "blackwell_telemetry.h"
#include <stdexcept>
#include <fcntl.h>
#include <unistd.h>
#include <chrono>

BlackwellTelemetryDriver::BlackwellTelemetryDriver(const std::string& pci_address) 
    : pci_addr(pci_address), fd(-1), bar0((uint8_t*)MAP_FAILED) {
    
    std::string resource_path = "/sys/bus/pci/devices/" + pci_address + "/resource0";
    
    fd = open(resource_path.c_str(), O_RDWR | O_SYNC);
    if (fd < 0) {
        throw std::runtime_error("APEX_CRITICAL: Failed to open Blackwell PCI resource: " + resource_path);
    }

    bar0 = (uint8_t*)mmap(NULL, NV_BAR0_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (bar0 == MAP_FAILED) {
        close(fd);
        throw std::runtime_error("APEX_CRITICAL: Failed to map BAR0 for Blackwell GPU at " + pci_address);
    }
}

BlackwellTelemetryDriver::~BlackwellTelemetryDriver() {
    if (bar0 != MAP_FAILED) munmap(bar0, NV_BAR0_SIZE);
    if (fd >= 0) close(fd);
}

BlackwellMetrics BlackwellTelemetryDriver::sample() {
    BlackwellMetrics m;
    
    // Low-latency direct register reads
    uint32_t t0 = read_reg(NV_PTHERM_DIE0_TEMP);
    uint32_t t1 = read_reg(NV_PTHERM_DIE1_TEMP);
    uint32_t p_mw = read_reg(NV_PPOWER_USAGE_MW);

    // Decode Blackwell thermal sensors (9-bit representation)
    m.temp_die0 = static_cast<float>(t0 & 0x1FF);
    m.temp_die1 = static_cast<float>(t1 & 0x1FF);
    
    // Scale milliwatts to Watts
    m.power_watts = static_cast<float>(p_mw) / 1000.0f;
    
    // High-resolution timestamp for LSTM sequence ordering
    m.timestamp = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();

    return m;
}
