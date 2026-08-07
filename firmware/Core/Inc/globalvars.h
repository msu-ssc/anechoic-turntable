/*
 * globalvars.h
 *
 *  Created on: Sep 18, 2024
 *      Author: ejensen
 */

#ifndef GLOBALVARS_H_
#define GLOBALVARS_H_

#include <stdint.h>

static const float MIN_PAN_DEG = -180.0f;
static const float MAX_PAN_DEG = 180.0f;

static const float MIN_MOVE_TILT_DEG = -90.0f;
static const float MAX_MOVE_TILT_DEG = 45.0f;

static const float MIN_SET_TILT_DEG = -90.0f;
static const float MAX_SET_TILT_DEG = 90.0f;

static const uint32_t MAX_POSITION_CHANGE_COUNTS = 240U;

#endif /* GLOBALVARS_H_ */
