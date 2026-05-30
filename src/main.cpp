#include <iostream>
#include <vector>
#include <thread>
#include <iomanip>
#include "blackwell_telemetry.h"

/**
 * APEX Nanosphere Collector
 * High-speed telemetry ingestion for Colossus 2.
 */

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cout << "Usage: apex_collector <PCI_ADDR>" << std::endl;
        return 1;
    }

    try {
        BlackwellTelemetryDriver driver(argv[1]);
        std::cout << "--------------------------------------------------" << std::endl;
        std::cout << "🚀 APEX NANOSPHERE COLLECTOR ACTIVE [GB200 NVL72]" << std::endl;
        std::cout << "Monitoring PCIe Address: " << argv[1] << std::endl;
        std::cout << "--------------------------------------------------" << std::endl;

        while (true) {
            auto metrics = driver.sample();
            
            // Format output for real-time visualization or log to .shadow
            std::cout << "\r[TS: " << metrics.timestamp << "] "
                      << "Die0: " << std::fixed << std::setprecision(1) << metrics.temp_die0 << "°C | "
                      << "Die1: " << metrics.temp_die1 << "°C | "
                      << "Power: " << metrics.power_watts << "W" << std::flush;
            
            // 1ms target sampling rate
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    } catch (const std::exception& e) {
        std::cerr << "\n🔥 APEX_FATAL: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
