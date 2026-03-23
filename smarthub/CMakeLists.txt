cmake_minimum_required(VERSION 3.16)
project(omni-hub C)

set(CMAKE_C_STANDARD 11)

# Find dependencies
find_package(PkgConfig REQUIRED)
pkg_check_modules(SDL2 REQUIRED sdl2)
pkg_check_modules(SDL2_TTF REQUIRED SDL2_ttf)
pkg_check_modules(CURL REQUIRED libcurl)

add_executable(omni-hub
    src/main.c
    src/keyboard.c
    src/login.c
    src/background.c
)

# Link math library for sin/cos/sqrt
target_link_libraries(omni-hub PRIVATE m)

target_include_directories(omni-hub PRIVATE
    ${SDL2_INCLUDE_DIRS}
    ${SDL2_TTF_INCLUDE_DIRS}
    ${CURL_INCLUDE_DIRS}
)

target_link_libraries(omni-hub PRIVATE
    ${SDL2_LIBRARIES}
    ${SDL2_TTF_LIBRARIES}
    ${CURL_LIBRARIES}
    pthread
)

target_compile_options(omni-hub PRIVATE -Wall -Wextra -O2)

install(TARGETS omni-hub DESTINATION bin)
