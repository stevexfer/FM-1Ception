# Cross-compile FM-1Ception for Linux x86_64 from another Linux host (e.g. the aarch64 Ubuntu VM).
#
# Needs Debian/Ubuntu multiarch set up for amd64 with the JUCE dev libraries installed for it
# (g++-x86-64-linux-gnu, libasound2-dev:amd64, libfreetype-dev:amd64, libx11-dev:amd64,
# libxrandr-dev:amd64, libxinerama-dev:amd64, libxcursor-dev:amd64, libxext-dev:amd64,
# libgl-dev:amd64, libfontconfig-dev:amd64, libcurl4-openssl-dev:amd64, and rustup target
# x86_64-unknown-linux-gnu).
#
#   cmake -S fm1ception -B build-linux-x86_64 -G Ninja -DCMAKE_BUILD_TYPE=Release \
#         -DCMAKE_TOOLCHAIN_FILE=fm1ception/cmake/toolchains/linux-x86_64.cmake

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR x86_64)

set(_triple "x86_64-linux-gnu")

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

set(CMAKE_C_FLAGS_INIT   "-m64")
set(CMAKE_CXX_FLAGS_INIT "-m64")