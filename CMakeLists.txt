cmake_minimum_required(VERSION 3.10)
project(apex_nanosphere)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include_directories(include)

add_executable(apex_collector 
    src/main.cpp 
    src/telemetry/blackwell_telemetry.cpp
)

# Optimization for Ring -3 performance
target_compile_options(apex_collector PRIVATE -O3 -march=native -Wall)
