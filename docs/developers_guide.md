# Developer guide

## STM32 toolchain PATH

VS Code resolves `arm-none-eabi-gcc` through the environment it inherits when
it starts. Add the pinned STM32 toolchain's `bin` directory to `PATH` in
`~/.profile`, using the installation path for your machine:

```sh
STM32_GCC_BIN="/path/to/gnu-tools-for-stm32/tools/bin"
case ":$PATH:" in
    *":$STM32_GCC_BIN:"*) ;;
    *) PATH="$STM32_GCC_BIN:$PATH" ;;
esac
export PATH
unset STM32_GCC_BIN
```

Log out and back in so GUI-launched applications inherit the change. Then
restart VS Code and verify the setup with `command -v arm-none-eabi-gcc` in its
integrated terminal. The required toolchain version is documented in
[Firmware build](firmware-build.md).
