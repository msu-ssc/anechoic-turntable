/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2024 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "firmware_version.h"
#include "globalvars.h"
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
TIM_HandleTypeDef htim1;
TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;

UART_HandleTypeDef huart1;

/* USER CODE BEGIN PV */

/** Maximum command payload length before the terminating semicolon. */
enum { RECEIVE_FRAME_CAPACITY = 64 };

/** Motor axis identifiers used by driveAxis(). */
typedef enum
{
    AXIS_PAN = 1,
    AXIS_TILT = 2
} MotorAxis;

/** Direction relative to increasing or decreasing encoder counts. */
typedef enum
{
    DIRECTION_DECREASING,
    DIRECTION_INCREASING
} MotorDirection;

/** Command variants recognized after UART framing removes the semicolon. */
typedef enum
{
    COMMAND_UNKNOWN,
    COMMAND_SET,
    COMMAND_MOV,
    COMMAND_MOV_CNT,
    COMMAND_SET_CNT,
    COMMAND_VERSION,
    COMMAND_CNT
} CommandType;

/** Latest pan encoder sample. */
static uint32_t panPositionCounter = 0;

/** Latest tilt encoder sample. */
static uint32_t tiltPositionCounter = 0;

/** Latest pan position converted from the encoder sample. */
static float panPositionDegrees = 0.0f;

/** Latest tilt position converted from the encoder sample. */
static float tiltPositionDegrees = 0.0f;

/** PWM compare value currently requested for the pan motor. */
static int panPwmPowerLevel = INITIAL_PWM_POWER_LEVEL;

/** PWM compare value currently requested for the tilt motor. */
static int tiltPwmPowerLevel = INITIAL_PWM_POWER_LEVEL;

/** Most recently accepted pan movement command, retained for legacy reporting. */
static float commandedPanDegrees = 0.0f;

/** Most recently accepted tilt movement command, retained for legacy reporting. */
static float commandedTiltDegrees = 0.0f;

/** Active pan target used by the motor controller. */
static float targetPanDegrees = 0.0f;

/** Active tilt target used by the motor controller. */
static float targetTiltDegrees = 0.0f;

/** True while an accepted movement command is active. */
static bool movementActive = false;

/** HAL tick when the current movement command began. */
static uint32_t movementStartedTick = 0U;

/** True when pan is within TARGET_TOLERANCE_DEG of its target. */
static bool panTargetReached = false;

/** True when tilt is within TARGET_TOLERANCE_DEG of its target. */
static bool tiltTargetReached = false;

/** Bytes accumulated for the frame currently arriving over UART. */
static char receiveFrameBuffer[RECEIVE_FRAME_CAPACITY];

/** Completed command plus one byte for its C string terminator. */
static char pendingCommandBuffer[sizeof(receiveFrameBuffer) + 1U];

/** Number of payload bytes currently stored in receiveFrameBuffer. */
static int receiveFrameLength = 0;

/**
 * Command state shared with the UART ISR: 0 for none, 1 for ready, and -1 for
 * an oversized frame. Volatile is required because the ISR changes it.
 */
static volatile int pendingCommandState = 0;

/** Latest byte received by the interrupt-driven UART reader. */
static uint8_t receivedByte = 0;

/** True while ignoring an oversized frame until its terminating semicolon. */
static bool discardingOversizedFrame = false;

/** Number of complete frames rejected because another command was pending. */
static volatile uint32_t rejectedFrameCount = 0;

/** Number of interrupted or oversized frames awaiting a parse-failure NAK. */
static volatile uint32_t unableToParseFrameCount = 0;

/** Generation counter used to invalidate commands copied before a stop byte. */
static volatile uint32_t stopGeneration = 0;

/** Number of emergency-stop acknowledgements awaiting transmission. */
static volatile uint32_t emergencyStopAcknowledgementCount = 0;

/** Previous pan encoder sample used for discontinuity detection. */
static uint32_t previousPanCounter = 0;

/** Previous tilt encoder sample used for discontinuity detection. */
static uint32_t previousTiltCounter = 0;

/** True after the discontinuity detector has captured its first baseline. */
static bool positionDiscontinuityBaselineValid = false;

/** Exact VERSION response assembled from the canonical firmware version. */
static const char firmwareVersionMessage[] = "MSG:VERSION:" FIRMWARE_VERSION ";\r\n";

/** Exact fail-safe report sent after an implausible encoder jump. */
static const char positionDiscontinuityMessage[] = "MSG:ERR:POSITION_DISCONTINUITY;\r\n";

/** Exact fail-safe report sent when movement exceeds its deadline. */
static const char movementTimeoutMessage[] = "MSG:ERR:MOVEMENT_TIMEOUT;\r\n";

/** Exact fail-safe report sent when a commanded axis stops changing. */
static const char movementStalledMessage[] = "MSG:ERR:MOVEMENT_STALLED;\r\n";

/** Pan encoder counter captured by the previous movement-progress check. */
static uint32_t panCounterAtLastMovementCheck = 0U;

/** Tilt encoder counter captured by the previous movement-progress check. */
static uint32_t tiltCounterAtLastMovementCheck = 0U;

/** HAL tick when the next movement-progress check is due. */
static uint32_t nextMovementCheckTick = 0U;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_TIM1_Init(void);
static void MX_TIM2_Init(void);
static void MX_TIM3_Init(void);
static void MX_USART1_UART_Init(void);
/* USER CODE BEGIN PFP */

static void delayMilliseconds(uint32_t milliseconds);
static void enablePanMotor(void);
static void disablePanMotor(void);
static void enableTiltMotor(void);
static void disableTiltMotor(void);
static void sendData(const char *data, int size);
static void sendAcknowledgement(const char *command, bool accepted, const char *reason);
static bool counterChangeExceeds(uint32_t current, uint32_t previous, uint32_t maximumChange);
static float panCounterToDegrees(uint32_t counter);
static uint32_t panDegreesToCounter(float degrees);
static float tiltCounterToDegrees(uint32_t counter);
static uint32_t tiltDegreesToCounter(float degrees);
static bool isAsciiDigit(char character);
static int parseWireNumber(const char *text, float *parsedValue);
static int parseCounterNumber(const char *text, uint32_t *parsedValue);
static bool parseCommandCoordinates(const char *input, const char *expectedPrefix, float *pan, float *tilt);
static bool parseMoveCommand(const char *input, float *pan, float *tilt);
static bool parseSetCommand(const char *input, float *pan, float *tilt);
static bool parseCounterCommand(
        const char *input,
        const char *expectedPrefix,
        uint32_t *panCounter,
        uint32_t *tiltCounter);
static bool commandTokenMatches(const char *input, const char *token);
static CommandType identifyCommandType(const char *input);
static const char *commandTypeName(CommandType commandType);
static void runMainLoopIteration(void);
static void driveAxis(MotorAxis axis, int pwmPowerLevel, MotorDirection direction);
static void updateMotorControl(void);
static void resetMovementStallWatchdog(uint32_t currentTick);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/**
 * @brief Consume one received UART byte and restart interrupt reception.
 *
 * The emergency-stop byte is handled before normal framing so stopping never
 * waits for the main loop. Complete commands remain stable until copied.
 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    (void)huart;

    if (receivedByte == 'p')
    {
        if (pendingCommandState == 1 && rejectedFrameCount < UINT32_MAX)
        {
            rejectedFrameCount++;
        }
        if ((pendingCommandState == -1 || receiveFrameLength > 0 || discardingOversizedFrame) &&
                unableToParseFrameCount < UINT32_MAX)
        {
            unableToParseFrameCount++;
        }

        pendingCommandState = 0;
        stopGeneration++;
        if (emergencyStopAcknowledgementCount < UINT32_MAX)
        {
            emergencyStopAcknowledgementCount++;
        }

        movementActive = false;
        receivedByte = 0;
        disablePanMotor();
        disableTiltMotor();

        /* Bytes before a stop must never become part of the next command. */
        receiveFrameLength = 0;
        memset(receiveFrameBuffer, 0, sizeof(receiveFrameBuffer));
        memset(pendingCommandBuffer, 0, sizeof(pendingCommandBuffer));
        discardingOversizedFrame = false;
    }
    else if (discardingOversizedFrame)
    {
        /* An invalid frame remains discarded through its terminating semicolon. */
        if (receivedByte == ';')
        {
            discardingOversizedFrame = false;
            if (pendingCommandState == 0)
            {
                pendingCommandState = -1;
            }
            else if (rejectedFrameCount < UINT32_MAX)
            {
                rejectedFrameCount++;
            }
        }
    }
    else if (receivedByte == ';')
    {
        /* Do not overwrite a complete command before the main loop copies it. */
        if (pendingCommandState == 0)
        {
            memcpy(pendingCommandBuffer, receiveFrameBuffer, (size_t)receiveFrameLength);
            pendingCommandBuffer[receiveFrameLength] = '\0';
            pendingCommandState = 1;
        }
        else if (rejectedFrameCount < UINT32_MAX)
        {
            rejectedFrameCount++;
        }

        receiveFrameLength = 0;
        memset(receiveFrameBuffer, 0, sizeof(receiveFrameBuffer));
    }
    else if (receiveFrameLength >= (int)sizeof(receiveFrameBuffer))
    {
        /* Check before writing so an oversized frame cannot overflow the buffer. */
        receiveFrameLength = 0;
        memset(receiveFrameBuffer, 0, sizeof(receiveFrameBuffer));
        discardingOversizedFrame = true;
    }
    else
    {
        receiveFrameBuffer[receiveFrameLength] = (char)receivedByte;
        receiveFrameLength++;
    }

    receivedByte = 0;
    HAL_UART_Receive_IT(&huart1, &receivedByte, 1);
}

/** @brief Return true only for an ASCII decimal digit. */
static bool isAsciiDigit(char character)
{
    return character >= '0' && character <= '9';
}

/**
 * @brief Parse one canonical signed wire number with exactly three decimals.
 * @return The number of consumed characters, or -1 when malformed.
 */
static int parseWireNumber(const char *text, float *parsedValue)
{
    int index = 0;
    if (text[index] == '-')
    {
        index++;
    }

    int integerStart = index;
    while (isAsciiDigit(text[index]))
    {
        index++;
    }
    if (index == integerStart)
    {
        return -1;
    }

    if (text[index] != '.' ||
            !isAsciiDigit(text[index + 1]) ||
            !isAsciiDigit(text[index + 2]) ||
            !isAsciiDigit(text[index + 3]) ||
            isAsciiDigit(text[index + 4]))
    {
        return -1;
    }
    index += 4;

    float value = 0.0f;
    int convertedLength = 0;
    /* %n records how many characters sscanf consumed while parsing the float. */
    int convertedValueCount = sscanf(text, "%f%n", &value, &convertedLength);
    if (convertedValueCount != 1 || convertedLength != index || !isfinite(value))
    {
        return -1;
    }
    if (text[0] == '-' && value == 0.0f)
    {
        return -1;
    }

   *parsedValue = value;
    return index;
}

/**
 * @brief Parse one canonical unsigned decimal encoder count.
 * @return The number of consumed characters, or -1 when malformed or too large.
 */
static int parseCounterNumber(const char *text, uint32_t *parsedValue)
{
    int index = 0;
    uint32_t value = 0;

    if (!isAsciiDigit(text[index]) ||
            (text[index] == '0' && isAsciiDigit(text[index + 1])))
    {
        return -1;
    }

    while (isAsciiDigit(text[index]))
    {
        uint32_t digit = (uint32_t)(text[index] - '0');
        if (value > (UINT32_MAX - digit) / 10U)
        {
            return -1;
        }

        value = (value * 10U) + digit;
        index++;
    }

   *parsedValue = value;
    return index;
}

/** @brief Parse the two coordinates from a complete MOV or SET command. */
static bool parseCommandCoordinates(
        const char *input,
        const char *expectedPrefix,
        float *pan,
        float *tilt)
{
    size_t prefixLength = strlen(expectedPrefix);
    if (strncmp(input, expectedPrefix, prefixLength) != 0)
    {
        return false;
    }

    const char *coordinateText = input + prefixLength;
    float parsedPan = 0.0f;
    int panLength = parseWireNumber(coordinateText, &parsedPan);
    if (panLength < 0 || coordinateText[panLength] != ',')
    {
        return false;
    }

    const char *tiltText = coordinateText + panLength + 1;
    float parsedTilt = 0.0f;
    int tiltLength = parseWireNumber(tiltText, &parsedTilt);
    if (tiltLength < 0 || tiltText[tiltLength] != '\0')
    {
        return false;
    }

    /* Do not expose partially parsed coordinates after any parse failure. */
   *pan = parsedPan;
   *tilt = parsedTilt;
    return true;
}

/** @brief Parse an exact CMD:MOV coordinate payload. */
static bool parseMoveCommand(const char *input, float *pan, float *tilt)
{
    return parseCommandCoordinates(input, "CMD:MOV:", pan, tilt);
}

/** @brief Parse an exact CMD:SET coordinate payload. */
static bool parseSetCommand(const char *input, float *pan, float *tilt)
{
    return parseCommandCoordinates(input, "CMD:SET:", pan, tilt);
}

/** @brief Parse the exact PAN and TILT fields of a counter command. */
static bool parseCounterCommand(
        const char *input,
        const char *expectedPrefix,
        uint32_t *panCounter,
        uint32_t *tiltCounter)
{
    static const char expectedSeparator[] = ",TILT=";
    size_t prefixLength = strlen(expectedPrefix);

    if (strncmp(input, expectedPrefix, prefixLength) != 0)
    {
        return false;
    }

    const char *counterText = input + prefixLength;
    uint32_t parsedPan = 0;
    int panLength = parseCounterNumber(counterText, &parsedPan);
    if (panLength < 0 ||
            strncmp(counterText + panLength, expectedSeparator,
                            sizeof(expectedSeparator) - 1U) != 0)
    {
        return false;
    }

    const char *tiltText = counterText + panLength + sizeof(expectedSeparator) - 1U;
    uint32_t parsedTilt = 0;
    int tiltLength = parseCounterNumber(tiltText, &parsedTilt);
    if (tiltLength < 0 || tiltText[tiltLength] != '\0')
    {
        return false;
    }

   *panCounter = parsedPan;
   *tiltCounter = parsedTilt;
    return true;
}

/** @brief Return true when a command starts with one exact command token. */
static bool commandTokenMatches(const char *input, const char *token)
{
    static const char commandPrefix[] = "CMD:";
    size_t tokenLength = strlen(token);
    if (strncmp(input, commandPrefix, sizeof(commandPrefix) - 1U) != 0 ||
            strncmp(input + sizeof(commandPrefix) - 1U, token, tokenLength) != 0)
    {
        return false;
    }

    char nextCharacter = input[sizeof(commandPrefix) - 1U + tokenLength];
    return nextCharacter == ':' || nextCharacter == '\0';
}

/** @brief Identify the command token without accepting ambiguous prefixes. */
static CommandType identifyCommandType(const char *input)
{
    if (commandTokenMatches(input, "MOV_CNT"))
    {
        return COMMAND_MOV_CNT;
    }
    if (commandTokenMatches(input, "SET_CNT"))
    {
        return COMMAND_SET_CNT;
    }
    if (commandTokenMatches(input, "VERSION"))
    {
        return COMMAND_VERSION;
    }
    if (commandTokenMatches(input, "SET"))
    {
        return COMMAND_SET;
    }
    if (commandTokenMatches(input, "MOV"))
    {
        return COMMAND_MOV;
    }
    if (commandTokenMatches(input, "CNT"))
    {
        return COMMAND_CNT;
    }
    return COMMAND_UNKNOWN;
}

/** @brief Return the protocol token used in an acknowledgement. */
static const char *commandTypeName(CommandType commandType)
{
    switch (commandType)
    {
        case COMMAND_SET:
            return "SET";
        case COMMAND_MOV:
            return "MOV";
        case COMMAND_MOV_CNT:
            return "MOV_CNT";
        case COMMAND_SET_CNT:
            return "SET_CNT";
        case COMMAND_VERSION:
            return "VERSION";
        case COMMAND_CNT:
            return "CNT";
        default:
            return "UNKNOWN";
    }
}



/** @brief Delay execution for the requested number of milliseconds. */
static void delayMilliseconds(uint32_t milliseconds)
{
    HAL_Delay(milliseconds);
}

/** @brief Energize the pan motor driver. */
static void enablePanMotor(void)
{
    HAL_GPIO_WritePin(GPIOE, ENABLE_A_Pin, GPIO_PIN_SET);
}

/** @brief De-energize pan and clear both pan PWM channels. */
static void disablePanMotor(void)
{
    HAL_GPIO_WritePin(GPIOE, ENABLE_A_Pin, GPIO_PIN_RESET);
    TIM3->CCR1 = 0;
    TIM3->CCR2 = 0;
    panTargetReached = false;
}

/** @brief Energize both tilt motor-driver enable lines. */
static void enableTiltMotor(void)
{
    HAL_GPIO_WritePin(GPIOE, ENABLE_E_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(GPIOB, ENABLE_EE_Pin, GPIO_PIN_SET);
}

/** @brief De-energize tilt and clear both tilt PWM channels. */
static void disableTiltMotor(void)
{
    HAL_GPIO_WritePin(GPIOE, ENABLE_E_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GPIOB, ENABLE_EE_Pin, GPIO_PIN_RESET);
    TIM3->CCR4 = 0;
    TIM3->CCR3 = 0;
    tiltTargetReached = false;
}

/** @brief Transmit an exact byte range over the controller UART. */
static void sendData(const char *data, int size)
{
    HAL_UART_Transmit(
            &huart1,
            (uint8_t *)data,
            (uint16_t)size,
            UART_TRANSMIT_TIMEOUT_MS);
}

/** @brief Format and send an ACK or NAK for one command token. */
static void sendAcknowledgement(const char *command, bool accepted, const char *reason)
{
    char acknowledgement[RECEIVE_FRAME_CAPACITY];
    int acknowledgementLength;

    if (accepted)
    {
        acknowledgementLength = snprintf(
                acknowledgement,
                sizeof(acknowledgement),
                "MSG:ACK:%s;\r\n",
                command);
    }
    else
    {
        acknowledgementLength = snprintf(
                acknowledgement,
                sizeof(acknowledgement),
                "MSG:NAK:%s,%s;\r\n",
                command,
                reason);
    }

    if (acknowledgementLength > 0 &&
            acknowledgementLength < (int)sizeof(acknowledgement))
    {
        sendData(acknowledgement, acknowledgementLength);
    }
}

/** @brief Return true when two encoder samples differ by an unsafe amount. */
static bool counterChangeExceeds(
        uint32_t current,
        uint32_t previous,
        uint32_t maximumChange)
{
    uint32_t change = current >= previous ? current - previous : previous - current;
    return change > maximumChange;
}

/** @brief Convert a raw pan encoder count to firmware-relative degrees. */
static float panCounterToDegrees(uint32_t counter)
{
    return ((float)counter - (float)PAN_ZERO_DEGREE_COUNTER) / PAN_COUNTS_PER_DEGREE;
}

/** @brief Convert firmware-relative pan degrees to a raw encoder count. */
static uint32_t panDegreesToCounter(float degrees)
{
    return (uint32_t)((float)PAN_ZERO_DEGREE_COUNTER + (degrees * PAN_COUNTS_PER_DEGREE));
}

/** @brief Convert a raw tilt encoder count to firmware-relative degrees. */
static float tiltCounterToDegrees(uint32_t counter)
{
    return ((float)counter - (float)TILT_ZERO_DEGREE_COUNTER) / TILT_COUNTS_PER_DEGREE;
}

/** @brief Convert firmware-relative tilt degrees to a raw encoder count. */
static uint32_t tiltDegreesToCounter(float degrees)
{
    return (uint32_t)((float)TILT_ZERO_DEGREE_COUNTER + (degrees * TILT_COUNTS_PER_DEGREE));
}

/** @brief Execute one sample, command-processing, and reporting iteration. */
static void runMainLoopIteration(void)
{
    float setPanDegrees = 0.0f;
    float setTiltDegrees = 0.0f;
    char sendBuffer[RECEIVE_FRAME_CAPACITY];
    char commandToProcess[sizeof(pendingCommandBuffer)];
    bool commandAvailable = false;
    bool oversizedCommandAvailable = false;
    bool rejectedFrameAvailable = false;
    bool unableToParseFrameAvailable = false;
    bool emergencyStopAcknowledgementAvailable = false;
    bool positionDiscontinuityDetected = false;
    bool movementTimeoutDetected = false;
    bool movementStallDetected = false;
    uint32_t currentTick = HAL_GetTick();
    uint32_t copiedStopGeneration = 0;

    panPositionCounter = TIM2->CNT;
    tiltPositionCounter = TIM1->CNT;

    /* Any implausible encoder jump during motion immediately fails safe. */
    if (positionDiscontinuityBaselineValid && movementActive &&
            (counterChangeExceeds(
                      panPositionCounter,
                      previousPanCounter,
                      MAX_POSITION_CHANGE_COUNTS) ||
              counterChangeExceeds(
                      tiltPositionCounter,
                      previousTiltCounter,
                      MAX_POSITION_CHANGE_COUNTS)))
    {
        movementActive = false;
        disablePanMotor();
        disableTiltMotor();
        positionDiscontinuityDetected = true;
    }
    previousPanCounter = panPositionCounter;
    previousTiltCounter = tiltPositionCounter;
    positionDiscontinuityBaselineValid = true;

    panPositionDegrees = panCounterToDegrees(panPositionCounter);
    tiltPositionDegrees = tiltCounterToDegrees(tiltPositionCounter);
    bool panShouldMove =
            fabsf(panPositionDegrees - targetPanDegrees) > TARGET_TOLERANCE_DEG;
    bool tiltShouldMove =
            fabsf(tiltPositionDegrees - targetTiltDegrees) > TARGET_TOLERANCE_DEG;
    bool targetReachedAtCurrentSample = !panShouldMove && !tiltShouldMove;

    // Check if there is a stall.
    if (movementActive &&
            (int32_t)(currentTick - nextMovementCheckTick) >= 0)
    {
        bool panStalled = panShouldMove &&
                panPositionCounter == panCounterAtLastMovementCheck;
        bool tiltStalled = tiltShouldMove &&
                tiltPositionCounter == tiltCounterAtLastMovementCheck;

        panCounterAtLastMovementCheck = panPositionCounter;
        tiltCounterAtLastMovementCheck = tiltPositionCounter;
        nextMovementCheckTick = currentTick + MOVEMENT_STALL_CHECK_INTERVAL_MS;

        if (panStalled || tiltStalled)
        {
            movementActive = false;
            disablePanMotor();
            disableTiltMotor();
            movementStallDetected = true;
        }
    }
    delayMilliseconds(MAIN_LOOP_DELAY_MS);

    /* Keep this critical section short so the ISR can resume framing quickly. */
    __disable_irq();
    if (pendingCommandState == 1)
    {
        memcpy(commandToProcess, pendingCommandBuffer, sizeof(commandToProcess));
        pendingCommandState = 0;
        copiedStopGeneration = stopGeneration;
        commandAvailable = true;
    }
    else if (pendingCommandState == -1)
    {
        pendingCommandState = 0;
        oversizedCommandAvailable = true;
    }
    if (rejectedFrameCount > 0)
    {
        rejectedFrameCount--;
        rejectedFrameAvailable = true;
    }
    if (unableToParseFrameCount > 0)
    {
        unableToParseFrameCount--;
        unableToParseFrameAvailable = true;
    }
    if (emergencyStopAcknowledgementCount > 0)
    {
        emergencyStopAcknowledgementCount--;
        emergencyStopAcknowledgementAvailable = true;
    }
    __enable_irq();

    if (oversizedCommandAvailable)
    {
        sendAcknowledgement("UNKNOWN", false, "UNABLE_TO_PARSE");
    }
    if (emergencyStopAcknowledgementAvailable)
    {
        sendAcknowledgement("EMERGENCY_STOP", true, NULL);
    }
    if (rejectedFrameAvailable)
    {
        sendAcknowledgement("UNKNOWN", false, "REJECTED");
    }
    if (unableToParseFrameAvailable)
    {
        sendAcknowledgement("UNKNOWN", false, "UNABLE_TO_PARSE");
    }

    if (commandAvailable)
    {
        /* Parsed values remain local until the complete command can be applied. */
        float requestedPan = 0.0f;
        float requestedTilt = 0.0f;
        uint32_t panCounter = 0;
        uint32_t tiltCounter = 0;
        CommandType commandType = identifyCommandType(commandToProcess);
        bool commandParsed = false;
        bool commandRejected = false;

        switch (commandType)
        {
            case COMMAND_MOV:
                commandParsed = parseMoveCommand(commandToProcess, &requestedPan, &requestedTilt);
                commandRejected = commandParsed &&
                        (requestedPan < MIN_PAN_DEG || requestedPan > MAX_PAN_DEG ||
                          requestedTilt < MIN_TILT_DEG || requestedTilt > MAX_TILT_DEG);
                break;
            case COMMAND_SET:
                commandParsed = parseSetCommand(commandToProcess, &setPanDegrees, &setTiltDegrees);
                commandRejected = commandParsed &&
                        (setPanDegrees < MIN_PAN_DEG || setPanDegrees > MAX_PAN_DEG ||
                          setTiltDegrees < MIN_TILT_DEG || setTiltDegrees > MAX_TILT_DEG);
                break;
            case COMMAND_VERSION:
                commandParsed = strcmp(commandToProcess, "CMD:VERSION") == 0;
                break;
            case COMMAND_CNT:
                commandParsed = strcmp(commandToProcess, "CMD:CNT") == 0;
                break;
            case COMMAND_MOV_CNT:
                commandParsed = parseCounterCommand(
                        commandToProcess,
                        "CMD:MOV_CNT:PAN=",
                        &panCounter,
                        &tiltCounter);
                break;
            case COMMAND_SET_CNT:
                commandParsed = parseCounterCommand(
                        commandToProcess,
                        "CMD:SET_CNT:PAN=",
                        &panCounter,
                        &tiltCounter);
                break;
            default:
                break;
        }

        bool commandCancelled = false;
        bool sendCounterResponse = false;

        /* A stop received during parsing invalidates the copied command. */
        __disable_irq();
        if (copiedStopGeneration != stopGeneration)
        {
            commandCancelled = true;
        }
        else if (!commandParsed || commandRejected)
        {
            movementActive = false;
            disablePanMotor();
            disableTiltMotor();
        }
        else
        {
            switch (commandType)
            {
                case COMMAND_CNT:
                    panCounter = TIM2->CNT;
                    tiltCounter = TIM1->CNT;
                    sendCounterResponse = true;
                    break;
                case COMMAND_SET_CNT:
                    movementActive = false;
                    disablePanMotor();
                    disableTiltMotor();
                    TIM2->CNT = panCounter;
                    TIM1->CNT = tiltCounter;
                    panCounter = TIM2->CNT;
                    tiltCounter = TIM1->CNT;
                    previousPanCounter = panCounter;
                    previousTiltCounter = tiltCounter;
                    positionDiscontinuityBaselineValid = true;
                    sendCounterResponse = true;
                    break;
                case COMMAND_MOV_CNT:
                    requestedPan = panCounterToDegrees(panCounter);
                    requestedTilt = tiltCounterToDegrees(tiltCounter);
                    /* fall through */
                case COMMAND_MOV:
                {
                    bool movementTargetChanged = !movementActive ||
                            requestedPan != targetPanDegrees ||
                            requestedTilt != targetTiltDegrees;
                    commandedPanDegrees = requestedPan;
                    commandedTiltDegrees = requestedTilt;
                    panTargetReached = false;
                    tiltTargetReached = false;
                    movementActive = true;
                    targetPanDegrees = commandedPanDegrees;
                    targetTiltDegrees = commandedTiltDegrees;
                    panPwmPowerLevel = MAX_PWM_POWER_LEVEL;
                    tiltPwmPowerLevel = MAX_PWM_POWER_LEVEL;
                    if (movementTargetChanged)
                    {
                        movementStartedTick = currentTick;
                        resetMovementStallWatchdog(currentTick);
                    }
                    break;
                }
                case COMMAND_SET:
                    movementActive = false;
                    TIM1->CNT = tiltDegreesToCounter(setTiltDegrees);
                    TIM2->CNT = panDegreesToCounter(setPanDegrees);
                    previousPanCounter = TIM2->CNT;
                    previousTiltCounter = TIM1->CNT;
                    positionDiscontinuityBaselineValid = true;
                    break;
                default:
                    break;
            }
        }
        __enable_irq();

        bool commandAccepted = !commandCancelled && commandParsed && !commandRejected;
        if (commandAccepted)
        {
            sendAcknowledgement(commandTypeName(commandType), true, NULL);
        }
        else
        {
            const char *reason = commandRejected
                    ? "OUT_OF_BOUNDS"
                    : (commandCancelled ? "REJECTED" : "UNABLE_TO_PARSE");
            sendAcknowledgement(commandTypeName(commandType), false, reason);
        }

        if (commandAccepted && sendCounterResponse)
        {
            int counterMessageLength = snprintf(
                    sendBuffer,
                    sizeof(sendBuffer),
                    "MSG:CNT:PAN=%lu,TILT=%lu;\r\n",
                    (unsigned long)panCounter,
                    (unsigned long)tiltCounter);
            if (counterMessageLength > 0 && counterMessageLength < (int)sizeof(sendBuffer))
            {
                sendData(sendBuffer, counterMessageLength);
            }
        }
        else if (commandAccepted && commandType == COMMAND_VERSION)
        {
            sendData(firmwareVersionMessage, (int)sizeof(firmwareVersionMessage) - 1);
        }
        else if (commandAccepted &&
                          (commandType == COMMAND_MOV ||
                            commandType == COMMAND_MOV_CNT ||
                            commandType == COMMAND_SET))
        {
            int commandMessageLength = snprintf(
                    sendBuffer,
                    sizeof(sendBuffer),
                    "%.2f , %.2f \r\n",
                    commandedPanDegrees,
                    commandedTiltDegrees);
            if (commandMessageLength > 0 && commandMessageLength < (int)sizeof(sendBuffer))
            {
                sendData(sendBuffer, commandMessageLength);
            }
        }
    }

    if (positionDiscontinuityDetected)
    {
        /* A command received in this loop must not restart motion after the fault. */
        movementActive = false;
        disablePanMotor();
        disableTiltMotor();
        sendData(
                positionDiscontinuityMessage,
                (int)sizeof(positionDiscontinuityMessage) - 1);
    }

    if (movementActive && !targetReachedAtCurrentSample &&
            (uint32_t)(currentTick - movementStartedTick) >= MOVEMENT_TIMEOUT_MS)
    {
        movementActive = false;
        disablePanMotor();
        disableTiltMotor();
        movementTimeoutDetected = true;
    }

    if (movementTimeoutDetected)
    {
        sendData(
                movementTimeoutMessage,
                (int)sizeof(movementTimeoutMessage) - 1);
    }

    if (movementStallDetected)
    {
        /* A command received in this loop must not restart motion after the fault. */
        movementActive = false;
        disablePanMotor();
        disableTiltMotor();
        sendData(
                movementStalledMessage,
                (int)sizeof(movementStalledMessage) - 1);
    }

    if (movementActive && !targetReachedAtCurrentSample)
    {
        updateMotorControl();
    }
    else
    {
        movementActive = false;
        disablePanMotor();
        disableTiltMotor();
    }

    int positionMessageLength = snprintf(
            sendBuffer,
            sizeof(sendBuffer),
            "MSG:POS:PAN=%.3f,TILT=%.3f\r\n",
            panPositionDegrees,
            tiltPositionDegrees);
    if (positionMessageLength > 0 && positionMessageLength < (int)sizeof(sendBuffer))
    {
        sendData(sendBuffer, positionMessageLength);
    }
}

/**
 * @brief Drive one motor axis in the requested encoder-count direction.
 *
 * TIM3 channels 1/2 drive pan in opposite directions; channels 3/4 do the
 * same for tilt. Disabling the axis before changing compare registers avoids
 * briefly energizing both directions at once.
 */
static void driveAxis(MotorAxis axis, int pwmPowerLevel, MotorDirection direction)
{
    if (axis == AXIS_PAN)
    {
        disablePanMotor();
        if (direction == DIRECTION_INCREASING)
        {
            TIM3->CCR2 = 0;
            TIM3->CCR1 = pwmPowerLevel;
        }
        else
        {
            TIM3->CCR1 = 0;
            TIM3->CCR2 = pwmPowerLevel;
        }
        enablePanMotor();
    }
    else if (axis == AXIS_TILT)
    {
        disableTiltMotor();
        if (direction == DIRECTION_INCREASING)
        {
            TIM3->CCR3 = pwmPowerLevel;
            TIM3->CCR4 = 0;
        }
        else
        {
            TIM3->CCR4 = pwmPowerLevel;
            TIM3->CCR3 = 0;
        }
        enableTiltMotor();
    }
    else
    {
        /* An invalid axis request fails safe by disabling both motors. */
        disableTiltMotor();
        disablePanMotor();
    }
}

/** @brief Update both motor outputs from the current position errors. */
static void updateMotorControl(void)
{
    float panDeviation = fabsf(panPositionDegrees - targetPanDegrees);
    float tiltDeviation = fabsf(tiltPositionDegrees - targetTiltDegrees);

    /* Reduce PWM near each target while retaining full power for long slews. */
    if (panPositionDegrees > targetPanDegrees - PAN_PWM_CONTROL_WINDOW_DEG &&
            panPositionDegrees < targetPanDegrees + PAN_PWM_CONTROL_WINDOW_DEG)
    {
        panPwmPowerLevel = (int)(panDeviation * PAN_PWM_COEFFICIENT + PAN_PWM_INTERCEPT);
    }
    else
    {
        panPwmPowerLevel = MAX_PWM_POWER_LEVEL;
    }

    if (tiltPositionDegrees > targetTiltDegrees - TILT_PWM_CONTROL_WINDOW_DEG &&
            tiltPositionDegrees < targetTiltDegrees + TILT_PWM_CONTROL_WINDOW_DEG)
    {
        tiltPwmPowerLevel = (int)(tiltDeviation * TILT_PWM_COEFFICIENT + TILT_PWM_INTERCEPT);
    }
    else
    {
        tiltPwmPowerLevel = MAX_PWM_POWER_LEVEL;
    }

    if (panPositionDegrees < targetPanDegrees - TARGET_TOLERANCE_DEG)
    {
        driveAxis(AXIS_PAN, panPwmPowerLevel, DIRECTION_INCREASING);
        panTargetReached = false;
    }
    else if (panPositionDegrees > targetPanDegrees + TARGET_TOLERANCE_DEG)
    {
        driveAxis(AXIS_PAN, panPwmPowerLevel, DIRECTION_DECREASING);
        panTargetReached = false;
    }
    else
    {
        disablePanMotor();
        panTargetReached = true;
    }

    if (tiltPositionDegrees < targetTiltDegrees - TARGET_TOLERANCE_DEG)
    {
        driveAxis(AXIS_TILT, tiltPwmPowerLevel, DIRECTION_INCREASING);
        tiltTargetReached = false;
    }
    else if (tiltPositionDegrees > targetTiltDegrees + TARGET_TOLERANCE_DEG)
    {
        driveAxis(AXIS_TILT, tiltPwmPowerLevel, DIRECTION_DECREASING);
        tiltTargetReached = false;
    }
    else
    {
        disableTiltMotor();
        tiltTargetReached = true;
    }
}

/** @brief Start both per-axis movement-stall timers from current counters. */
static void resetMovementStallWatchdog(uint32_t currentTick)
{
    panCounterAtLastMovementCheck = TIM2->CNT;
    tiltCounterAtLastMovementCheck = TIM1->CNT;
    nextMovementCheckTick = currentTick + MOVEMENT_STALL_CHECK_INTERVAL_MS;
}


/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_TIM1_Init();
  MX_TIM2_Init();
  MX_TIM3_Init();
  MX_USART1_UART_Init();
  /* USER CODE BEGIN 2 */

    TIM3->CCR1 = 0;
    TIM3->CCR2 = 0;
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_2);
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_3);
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_4);

    HAL_UART_Receive_IT(&huart1, &receivedByte, 1);
    HAL_TIM_Encoder_Start(&htim2, TIM_CHANNEL_ALL);
    HAL_TIM_Encoder_Start(&htim1, TIM_CHANNEL_ALL);

    disableTiltMotor();
    disablePanMotor();
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */

    runMainLoopIteration();

  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 4;
  RCC_OscInitStruct.PLL.PLLN = 168;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief TIM1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM1_Init(void)
{

  /* USER CODE BEGIN TIM1_Init 0 */

  /* USER CODE END TIM1_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM1_Init 1 */

  /* USER CODE END TIM1_Init 1 */
  htim1.Instance = TIM1;
  htim1.Init.Prescaler = 0;
  htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim1.Init.Period = 60000;
  htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim1.Init.RepetitionCounter = 0;
  htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 15;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 15;
  if (HAL_TIM_Encoder_Init(&htim1, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim1, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM1_Init 2 */

  /* USER CODE END TIM1_Init 2 */

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */

  /* USER CODE END TIM2_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 100000;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 15;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 15;
  if (HAL_TIM_Encoder_Init(&htim2, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */

}

/**
  * @brief TIM3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM3_Init(void)
{

  /* USER CODE BEGIN TIM3_Init 0 */

  /* USER CODE END TIM3_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM3_Init 1 */

  /* USER CODE END TIM3_Init 1 */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 64;
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 255;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim3, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_3) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM3_Init 2 */

  /* USER CODE END TIM3_Init 2 */
  HAL_TIM_MspPostInit(&htim3);

}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 9600;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
/* USER CODE BEGIN MX_GPIO_Init_1 */
/* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOE_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOE, ENABLE_E_Pin|ENABLE_A_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(ENABLE_EE_GPIO_Port, ENABLE_EE_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : ENABLE_E_Pin ENABLE_A_Pin */
  GPIO_InitStruct.Pin = ENABLE_E_Pin|ENABLE_A_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /*Configure GPIO pin : ENABLE_EE_Pin */
  GPIO_InitStruct.Pin = ENABLE_EE_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(ENABLE_EE_GPIO_Port, &GPIO_InitStruct);

/* USER CODE BEGIN MX_GPIO_Init_2 */
/* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}

#ifdef  USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
