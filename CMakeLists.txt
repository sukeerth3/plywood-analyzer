cmake_minimum_required(VERSION 3.22)
project(PlywoodAnalyzer LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

set(SRC ${CMAKE_SOURCE_DIR}/src/plywood_calc.cpp)

# Default debug build
add_executable(plywood_calc ${SRC})
target_compile_options(plywood_calc PRIVATE -Wall -Wextra -g -O0)

# Coverage build (gcov)
add_executable(plywood_calc_cov ${SRC})
target_compile_options(plywood_calc_cov PRIVATE -Wall -Wextra -g -O0 --coverage -fprofile-arcs -ftest-coverage)
target_link_options(plywood_calc_cov PRIVATE --coverage)

# LLVM IR emission
add_custom_target(emit_ir
    COMMAND clang++ -S -emit-llvm -g -O0 ${SRC} -o ${CMAKE_BINARY_DIR}/plywood_calc.ll
    COMMENT "Emitting LLVM IR"
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)

# Call graph extraction
add_custom_target(callgraph
    COMMAND opt -dot-callgraph ${CMAKE_BINARY_DIR}/plywood_calc.ll -o /dev/null 2>&1 || true
    COMMAND mv -f *.callgraph.dot ${CMAKE_BINARY_DIR}/ 2>/dev/null || true
    COMMENT "Extracting call graph via opt"
    DEPENDS emit_ir
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)

# CFG extraction
add_custom_target(cfg
    COMMAND opt -dot-cfg ${CMAKE_BINARY_DIR}/plywood_calc.ll -o /dev/null 2>&1 || true
    COMMAND mv -f .*.dot ${CMAKE_BINARY_DIR}/cfg/ 2>/dev/null || true
    COMMENT "Extracting CFGs via opt"
    DEPENDS emit_ir
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)

# Clang Static Analyzer
add_custom_target(static_analysis
    COMMAND scan-build --use-analyzer=clang++ -o ${CMAKE_BINARY_DIR}/scan-results clang++ -Wall -Wextra ${SRC} -o /dev/null 2>&1 | tee ${CMAKE_BINARY_DIR}/scan-build-output.txt
    COMMENT "Running Clang Static Analyzer"
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
