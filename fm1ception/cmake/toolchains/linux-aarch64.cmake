# Cross-compile FM-1Ception for Linux arm64 from an x86_64 Linux host.
#
# Needs g++-aarch64-linux-gnu, multiarch arm64 dev packages, and rustup target
# aarch64-unknown-linux-gnu.
#
#   cmake -S fm1ception -B build-linux-arm64 -G Ninja -DCMAKE_BUILD_TYPE=Release \
#         -DCMAKE_TOOLCHAIN_FILE=fm1ception/cmake/toolchains/linux-aarch64.cmake

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(_triple "aarch64-linux-gnu")

find_program(FM1C_CROSS_C_COMPILER   NAMES ${_triple}-gcc REQUIRED)
find_program(FM1C_CROSS_CXX_COMPILER NAMES ${_triple}-g++ REQUIRED)
set(CMAKE_C_COMPILER   "${FM1C_CROSS_C_COMPILER}"   CACHE FILEPATH "" FORCE)
set(CMAKE_CXX_COMPILER "${FM1C_CROSS_CXX_COMPILER}" CACHE FILEPATH "" FORCE)

set(ENV{PKG_CONFIG_ALLOW_CROSS} "1")
set(_pc_dirs "")
foreach(_d IN ITEMS "/usr/lib/${_triple}/pkgconfig" "/usr/${_triple}/lib/pkgconfig" "/usr/share/pkgconfig")
    if(EXISTS "${_d}")
        list(APPEND _pc_dirs "${_d}")
    endif()
endforeach()
list(JOIN _pc_dirs ":" _pc_libdir)
set(ENV{PKG_CONFIG_LIBDIR} "${_pc_libdir}")
set(ENV{PKG_CONFIG_PATH} "")

set(CMAKE_FIND_ROOT_PATH "/usr/${_triple}" "/usr")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)