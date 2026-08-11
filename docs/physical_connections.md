
## Connection summary

| MCU Signal     | AKA       | Firmware Function             | Connects To                                                   |
| -------------- | --------- | ----------------------------- | ------------------------------------------------------------- |
| PA6 / TIM3_CH1 | PWM_A      | Azimuth Direction 1 PWM       | Azimuth motor driver's first direction/control input          |
| PA7 / TIM3_CH2 | PWM_B      | Azimuth Direction 2 PWM       | Azimuth motor driver's second direction/control input<br>     |
| PE15           | ENABLE_A  | Azimuth enable, active high   | Azimuth motor driver enable input                             |
| PB0 / TIM3_CH3 | TIM3_CH3  | Elevation direction 1         | Elevation motor driver's first direction/control input<br>    |
| PB1 / TIM3_CH4 | TIM3_CH4  | Elevation direction 2 PWM     | Elevation motor driver's second direction/control input<br>   |
| PE14           | ENABLE_E  | Elevation enable, active high | Elevation motor driver enable input 1                         |
| PB10           | ENABLE_EE | Elevation enable, active high | Elevation motor driver enable input 2<br>                     |
| PA0            | TIM2_CH1  | Azimuth encoder channel A     | Azimuth quadrature encoder output A                           |
| PA1            | TIM2_CH2  | Azimuth encoder channel B     | Azimuth quadrature encoder output B<br>                       |
| PE9            | TIM1_CH1  | Elevation encoder channel A   | Elevation quadrature encoder output A<br>                     |
| PE11           | TIM1_CH2  | Elevation encoder channel B   | Elevation quadrature encoder output B<br>                     |
| PA9            | USART1_TX | Serial data from controller   | RX Input of the host/USB-to-UART adapter                      |
| PA10           | USART1_RX | Serial data to controller     | TX Output of the host/USB-to-UART adapter                     |
| GND            | Ground    | Signal Reference              | Ground of motor drivers, encoder interfaces, and UART adapter |

PA13 (SWDIO) and PA14 (SWCLK) remain assigned to the normal SWD programming interface. (But do not try to flash using PA13 and PA14.)
PH0 and PH1 are assigned to the external high-speed crystal or clock source.

## Flashing Connections



| ST-Link      | STM32 |
| ------------ | ----- |
| SWDIO        | SWDIO |
| SWCLK        | SWCLK |
| NRST         | NRST  |
| GND          | GND   |
| Optional 3.3 | 3.3   |
| BT0          | GND   |
| BT1          | GND   |


**CubeProgrammer settings:**

Port: SWD
Mode: Under reset
Reset mode: Hardware reset
SWD frequency: 400 kHz

