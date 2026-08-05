cmake_minimum_required(VERSION 3.22)
# Enable CMake support for ASM and C languages
enable_language(C ASM)

# Prefer the drivers stored with the project so a clean checkout builds on any
# host. CubeMX may remove those files when configured to reference its package
# repository, so retain a path-independent fallback for developer worktrees.
set(MX_Cube_F4_Version "STM32Cube_FW_F4_V1.28.1")
set(MX_Drivers_Dir "${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers")
set(MX_HAL_Probe "${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c")

if(NOT EXISTS "${MX_HAL_Probe}")
    set(MX_Cube_F4_Candidates
        "$ENV{STM32CUBE_F4_PATH}"
        "$ENV{HOME}/STM32Cube/Repository/${MX_Cube_F4_Version}"
        "$ENV{USERPROFILE}/STM32Cube/Repository/${MX_Cube_F4_Version}"
    )

    foreach(MX_Cube_F4_Dir IN LISTS MX_Cube_F4_Candidates)
        if(EXISTS "${MX_Cube_F4_Dir}/Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c")
            set(MX_Drivers_Dir "${MX_Cube_F4_Dir}/Drivers")
            break()
        endif()
    endforeach()

    if(NOT EXISTS "${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c")
        message(FATAL_ERROR
            "STM32F4 HAL sources were not found. Restore firmware/Drivers, or "
            "set STM32CUBE_F4_PATH to the ${MX_Cube_F4_Version} package directory."
        )
    endif()
endif()

# STM32CubeMX generated symbols (macros)
set(MX_Defines_Syms 
	USE_HAL_DRIVER 
	STM32F407xx
    $<$<CONFIG:Debug>:DEBUG>
)

# STM32CubeMX generated include paths
set(MX_Include_Dirs
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Inc
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Inc
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Inc/Legacy
    ${MX_Drivers_Dir}/CMSIS/Device/ST/STM32F4xx/Include
    ${MX_Drivers_Dir}/CMSIS/Include
)

# STM32CubeMX generated application sources
set(MX_Application_Src
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/main.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/stm32f4xx_it.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/stm32f4xx_hal_msp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/sysmem.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/syscalls.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Startup/startup_stm32f407vetx.s
)

# STM32 HAL/LL Drivers
set(STM32_Drivers_Src
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/system_stm32f4xx.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_tim.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_tim_ex.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_rcc.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_rcc_ex.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_flash.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_flash_ex.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_flash_ramfunc.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_gpio.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_dma_ex.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_dma.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pwr.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_pwr_ex.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_cortex.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_exti.c
    ${MX_Drivers_Dir}/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_uart.c
)

# Drivers Midllewares



# Link directories setup
set(MX_LINK_DIRS

)
# Project static libraries
set(MX_LINK_LIBS 
    STM32_Drivers
    ${TOOLCHAIN_LINK_LIBRARIES}
    
)
# Interface library for includes and symbols
add_library(stm32cubemx INTERFACE)
target_include_directories(stm32cubemx INTERFACE ${MX_Include_Dirs})
target_compile_definitions(stm32cubemx INTERFACE ${MX_Defines_Syms})

# Create STM32_Drivers static library
add_library(STM32_Drivers OBJECT)
target_sources(STM32_Drivers PRIVATE ${STM32_Drivers_Src})
target_link_libraries(STM32_Drivers PUBLIC stm32cubemx)


# Add STM32CubeMX generated application sources to the project
target_sources(${CMAKE_PROJECT_NAME} PRIVATE ${MX_Application_Src})

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE ${MX_LINK_DIRS})

# Add libraries to the project
target_link_libraries(${CMAKE_PROJECT_NAME} ${MX_LINK_LIBS})

# Add the map file to the list of files to be removed with 'clean' target
set_target_properties(${CMAKE_PROJECT_NAME} PROPERTIES ADDITIONAL_CLEAN_FILES ${CMAKE_PROJECT_NAME}.map)

# Validate that STM32CubeMX code is compatible with C standard
if((CMAKE_C_STANDARD EQUAL 90) OR (CMAKE_C_STANDARD EQUAL 99))
    message(ERROR "Generated code requires C11 or higher")
endif()
