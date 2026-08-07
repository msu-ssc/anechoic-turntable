/**
 * @file globalvars.h
 * @brief Physical limits, calibration values, and motor-control constants.
 */

#ifndef GLOBALVARS_H_
#define GLOBALVARS_H_

#include <stdint.h>

/** Smallest accepted physical pan angle, in degrees. */
static const float MIN_PAN_DEG = -180.0f;

/** Largest accepted physical pan angle, in degrees. */
static const float MAX_PAN_DEG = 180.0f;

/** Smallest accepted physical tilt angle, in degrees. */
static const float MIN_TILT_DEG = -90.0f;

/** Largest accepted physical tilt angle, in degrees. */
static const float MAX_TILT_DEG = 45.0f;

/** Maximum plausible encoder change between moving-loop samples. */
static const uint32_t MAX_POSITION_CHANGE_COUNTS = 240U;

/** Encoder count representing zero degrees of pan. */
static const uint32_t PAN_ZERO_DEGREE_COUNTER = 50000U;

/** Encoder count representing zero degrees of tilt. */
static const uint32_t TILT_ZERO_DEGREE_COUNTER = 30000U;

/** Pan encoder resolution in counts per degree. */
static const float PAN_COUNTS_PER_DEGREE = 240.0f;

/** Tilt encoder resolution in counts per degree. */
static const float TILT_COUNTS_PER_DEGREE = 240.0f;

/** Full-scale PWM compare value used while slewing either axis. */
static const int MAX_PWM_POWER_LEVEL = 255;

/** Initial PWM compare value before the first movement calculation. */
static const int INITIAL_PWM_POWER_LEVEL = 128;

/** Distance from the target where pan switches to proportional PWM. */
static const float PAN_PWM_CONTROL_WINDOW_DEG = 2.0f;

/** Slope of the pan proportional PWM calculation. */
static const float PAN_PWM_COEFFICIENT = 78.0f;

/** Minimum pan PWM compare value used near the target. */
static const float PAN_PWM_INTERCEPT = 99.0f;

/** Distance from the target where tilt switches to proportional PWM. */
static const float TILT_PWM_CONTROL_WINDOW_DEG = 2.0f;

/** Slope of the tilt proportional PWM calculation. */
static const float TILT_PWM_COEFFICIENT = 96.0f;

/** Minimum tilt PWM compare value used near the target. */
static const float TILT_PWM_INTERCEPT = 63.0f;

/** Allowed position error before an axis is considered on target. */
static const float TARGET_TOLERANCE_DEG = 0.1f;

/** Delay between main-loop iterations, in milliseconds. */
static const uint32_t MAIN_LOOP_DELAY_MS = 5U;

/** Maximum blocking time for one UART transmit, in milliseconds. */
static const uint32_t UART_TRANSMIT_TIMEOUT_MS = 1000U;

#endif /* GLOBALVARS_H_ */
