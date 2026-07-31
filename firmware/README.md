# LEMS Anechoic chamber turntable firmware

This is code written by Dr. Elijah Jensen. It was given to David Mayo by Jody
Caudill on 2025-02-17.

## Controller compatibility

The Python controller sends requested physical elevation directly as firmware
pitch; it no longer performs elevation-regime SET operations. Compatible
firmware therefore requires the expanded TIM1 encoder period of `43200`, with
zero elevation at count `21600`, as configured in `chambermotorcontrol.ioc` and
`Core/Src/main.c`.

Do not use the direct-coordinate controller with the historical TIM1 period of
`14400`. Its elevation counter cannot represent the controller's complete
`[-90°, 45°]` move range without rollover. The current bounds are inclusive and
do not yet provide an overshoot margin at exact counter endpoints.
