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
#include <string.h>
#include <stdio.h>
#include <stdbool.h>
#include <math.h>

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

void MYPROG_motor_control_loop();
void MYPROG_move_axis(int axis, int speed, int dir);
void MYPROG_disable_az();
void MYPROG_disable_el();

//global vars
int Az_pos;
int El_pos;


float Az_pos_deg;
float El_pos_deg;

int Az_speed =128;
int El_speed = 128;

float Azc =0;
float Elc =0;

float command_position_AZ=0;
float command_position_EL=0;

int move = 0;
int move_az =0;
int move_el = 0;

int mode =0;  // 0 is auto, 1 is manual

char rxBuffer[64];
// Completed commands are C strings, so they need one extra byte for the null terminator.
char rxBuffer_command[sizeof(rxBuffer) + 1];
int buffn =0;
// Indicates whether rxBuffer_command contains a command waiting for the main loop.
// volatile tells the compiler that the UART interrupt can change this value at any time.
volatile int command_read =0;
uint8_t buff;
bool discarding_oversized_frame = false;
volatile uint32_t rejected_frame_count = 0;
volatile uint32_t unable_to_parse_frame_count = 0;
// Incremented when the emergency-stop byte ('p') is received, allowing the
// main loop to recognize and cancel a command copied before the stop.
volatile uint32_t stop_generation = 0;
volatile uint32_t emergency_stop_ack_count = 0;
uint32_t previous_azimuth_counter = 0;
uint32_t previous_elevation_counter = 0;
bool position_discontinuity_baseline_valid = false;
static const char firmware_version_message[] = "MSG:VERSION:" FIRMWARE_VERSION ";\r\n";
static const char position_discontinuity_message[] = "MSG:ERR:POSITION_DISCONTINUITY;\r\n";

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  //You need to toggle a breakpoint on this line!
  //HAL_UART_Transmit(&huart1, rxBuffer, 32, 100);

  if(buff == 'a')
  {
	 // MYPROG_move_axis(1,0xFF,0);
	  buff = 0;
	  command_read =0;
	  mode = 1;

  }else if(buff == 'd')
  {
	//  MYPROG_move_axis(1,0xFF,1);
	  buff = 0;
	  command_read =0;
	  mode = 1;
  }else if(buff == 'w')
  {
	//  MYPROG_move_axis(2,0xFF,1);
	  buff = 0;
	  command_read =0;
	  mode = 1;
  }else if(buff == 's')
  {
	//  MYPROG_move_axis(2,0xFF,0);
	  buff = 0;
	  command_read =0;
	  mode = 1;
  }else if (buff == 'p')
  {
	  if (command_read == 1 && rejected_frame_count < UINT32_MAX)
	  {
		  rejected_frame_count++;
	  }
	  if ((command_read == -1 || buffn > 0 || discarding_oversized_frame) &&
		  unable_to_parse_frame_count < UINT32_MAX)
	  {
		  unable_to_parse_frame_count++;
	  }
	  command_read =0;
	  stop_generation++;
	  if (emergency_stop_ack_count < UINT32_MAX)
	  {
		  emergency_stop_ack_count++;
	  }
	  move = 0;
	  mode = 0;
	  buff =0;
	  MYPROG_disable_az();
	  MYPROG_disable_el();

	  // Example: after "CMD:MOV:10.000p", the bytes before p must not be reused.
	  buffn = 0;
	  memset(rxBuffer, 0, sizeof(rxBuffer));
	  memset(rxBuffer_command, 0, sizeof(rxBuffer_command));
	  discarding_oversized_frame = false;
  }else
  {

	  if (discarding_oversized_frame)
	  {
		  // The frame is already invalid. Ignore it until its terminating semicolon.
		  if (buff == ';')
		  {
			  discarding_oversized_frame = false;
			  if (command_read == 0)
			  {
				  command_read = -1;
			  }
			  else if (rejected_frame_count < UINT32_MAX)
			  {
				  rejected_frame_count++;
			  }
		  }
	  }
	  else if (buff == ';')
	  {
		  // Keep the existing command until the main loop has copied it.
		  if (command_read == 0)
		  {
			  memcpy(rxBuffer_command, rxBuffer, buffn);
			  rxBuffer_command[buffn] = '\0';
			  command_read = 1;
		  }
		  else if (rejected_frame_count < UINT32_MAX)
		  {
			  rejected_frame_count++;
		  }
		  buffn = 0;
		  memset(rxBuffer, 0, sizeof(rxBuffer));
	  }
	  else if (buffn >= (int)sizeof(rxBuffer))
	  {
		  // Check before writing so an oversized frame cannot overflow rxBuffer.
		  buffn = 0;
		  memset(rxBuffer, 0, sizeof(rxBuffer));
		  discarding_oversized_frame = true;
	  }
	  else
	  {
		  rxBuffer[buffn] = buff;
		  buffn++;
	  }

  }
  buff = 0;
  HAL_UART_Receive_IT(&huart1, &buff, 1);


}


bool is_ascii_digit(char character) {
    return character >= '0' && character <= '9';
}

// Parse one canonical wire number and return the number of characters it consumed.
// A negative return value means the number was malformed.
int parse_wire_number(const char *text, float *parsed_value) {
    int index = 0;
    if (text[index] == '-') {
        index++;
    }

    int integer_start = index;
    while (is_ascii_digit(text[index])) {
        index++;
    }
    if (index == integer_start) {
        return -1;
    }

    if (text[index] != '.' ||
        !is_ascii_digit(text[index + 1]) ||
        !is_ascii_digit(text[index + 2]) ||
        !is_ascii_digit(text[index + 3]) ||
        is_ascii_digit(text[index + 4])) {
        return -1;
    }
    index += 4;

    float value = 0.0f;
    int converted_length = 0;
    // %n records how many characters sscanf consumed while parsing the float.
    int converted_value_count = sscanf(text, "%f%n", &value, &converted_length);
    if (converted_value_count != 1) {
        return -1;
    }
    if (converted_length != index) {
        return -1;
    }
    if (!isfinite(value)) {
        return -1;
    }
    if (text[0] == '-' && value == 0.0f) {
        return -1;
    }

    *parsed_value = value;
    return index;
}

int parse_counter_number(const char *text, uint32_t *parsed_value)
{
    int index = 0;
    uint32_t value = 0;

    if (!is_ascii_digit(text[index])) {
        return -1;
    }
    if (text[index] == '0' && is_ascii_digit(text[index + 1])) {
        return -1;
    }

    while (is_ascii_digit(text[index])) {
        uint32_t digit =
            (uint32_t)(text[index] - '0');

        if (value > (UINT32_MAX - digit) / 10U) {
            return -1;
        }

        value = (value * 10U) + digit;
        index++;
    }

    *parsed_value = value;

    return index;
}

// Parse both coordinates from one complete command string.
// expected_prefix distinguishes commands such as "CMD:MOV:" and "CMD:SET:".
// Example input: "CMD:MOV:15.000,-40.000" (the receive callback removed the semicolon).
bool parse_command_coordinates(const char *input, const char *expected_prefix, float *yaw, float *pitch) {
    size_t prefix_length = strlen(expected_prefix);
    // The prefix must appear at the very beginning of the command.
    if (strncmp(input, expected_prefix, prefix_length) != 0) {
        return false;
    }

    // Skip the prefix, parse yaw, and require a comma immediately afterward.
    const char *coordinate_text = input + prefix_length;
    float parsed_yaw = 0.0f;
    int yaw_length = parse_wire_number(coordinate_text, &parsed_yaw);
    if (yaw_length < 0 || coordinate_text[yaw_length] != ',') {
        return false;
    }

    // Pitch begins after the comma and must consume the rest of the command.
    const char *pitch_text = coordinate_text + yaw_length + 1;
    float parsed_pitch = 0.0f;
    int pitch_length = parse_wire_number(pitch_text, &parsed_pitch);
    if (pitch_length < 0 || pitch_text[pitch_length] != '\0') {
        return false;
    }

    // Do not expose partially parsed coordinates when any part of the command is invalid.
    *yaw = parsed_yaw;
    *pitch = parsed_pitch;
    return true;
}

bool parse_mov_command(const char *input, float *yaw, float *pitch) {
    return parse_command_coordinates(input, "CMD:MOV:", yaw, pitch);
}

bool parse_set_command(const char *input, float *yaw, float *pitch) {
    return parse_command_coordinates(input, "CMD:SET:", yaw, pitch);
}

bool parse_counter_command(
    const char *input,
    const char *expected_prefix,
    uint32_t *azimuth_counter,
    uint32_t *elevation_counter
)
{
    static const char expected_separator[] = ",TILT=";

    size_t prefix_length = strlen(expected_prefix);

    if (strncmp(
            input,
            expected_prefix,
            prefix_length
        ) != 0) {
        return false;
    }

    const char *counter_text =
        input + prefix_length;

    uint32_t parsed_azimuth = 0;

    int azimuth_length = parse_counter_number(
        counter_text,
        &parsed_azimuth
    );

    if (azimuth_length < 0 ||
        strncmp(
            counter_text + azimuth_length,
            expected_separator,
            sizeof(expected_separator) - 1U
        ) != 0) {
        return false;
    }

    const char *elevation_text =
        counter_text + azimuth_length + sizeof(expected_separator) - 1U;

    uint32_t parsed_elevation = 0;

    int elevation_length = parse_counter_number(
        elevation_text,
        &parsed_elevation
    );

    if (elevation_length < 0 ||
        elevation_text[elevation_length] != '\0') {
        return false;
    }

    *azimuth_counter = parsed_azimuth;
    *elevation_counter = parsed_elevation;

    return true;
}

typedef enum
{
    COMMAND_UNKNOWN,
    COMMAND_SET,
    COMMAND_MOV,
    COMMAND_MOV_CNT,
    COMMAND_SET_CNT,
    COMMAND_VERSION,
    COMMAND_CNT
} command_type_t;

bool command_token_matches(const char *input, const char *token)
{
    static const char command_prefix[] = "CMD:";
    size_t token_length = strlen(token);
    if (strncmp(input, command_prefix, sizeof(command_prefix) - 1U) != 0 ||
        strncmp(input + sizeof(command_prefix) - 1U, token, token_length) != 0) {
        return false;
    }
    char next_character = input[sizeof(command_prefix) - 1U + token_length];
    return next_character == ':' || next_character == '\0';
}

command_type_t identify_command_type(const char *input)
{
    if (command_token_matches(input, "MOV_CNT")) {
        return COMMAND_MOV_CNT;
    }
    if (command_token_matches(input, "SET_CNT")) {
        return COMMAND_SET_CNT;
    }
    if (command_token_matches(input, "VERSION")) {
        return COMMAND_VERSION;
    }
    if (command_token_matches(input, "SET")) {
        return COMMAND_SET;
    }
    if (command_token_matches(input, "MOV")) {
        return COMMAND_MOV;
    }
    if (command_token_matches(input, "CNT")) {
        return COMMAND_CNT;
    }
    return COMMAND_UNKNOWN;
}

const char *command_type_name(command_type_t command_type)
{
    switch (command_type) {
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

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_TIM1_Init(void);
static void MX_TIM2_Init(void);
static void MX_TIM3_Init(void);
static void MX_USART1_UART_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */



//CDC_Receive_FS((uint8_t *)buffer,size);

void MYPROG_Delay(int milliseconds)
{
	HAL_Delay(milliseconds);
}

void MYPROG_enable_az()
{
	HAL_GPIO_WritePin(GPIOE, ENABLE_A_Pin, GPIO_PIN_SET);
}

void MYPROG_disable_az()
{
	HAL_GPIO_WritePin(GPIOE, ENABLE_A_Pin, GPIO_PIN_RESET);
	TIM3->CCR1 = 0;
	TIM3->CCR2 = 0;
	move_az = 0;
}

void MYPROG_enable_el()
{
	HAL_GPIO_WritePin(GPIOE, ENABLE_E_Pin, GPIO_PIN_SET);
	HAL_GPIO_WritePin(GPIOB, ENABLE_EE_Pin, GPIO_PIN_SET);
}

void MYPROG_disable_el()
{
	HAL_GPIO_WritePin(GPIOE, ENABLE_E_Pin, GPIO_PIN_RESET);
	HAL_GPIO_WritePin(GPIOB, ENABLE_EE_Pin, GPIO_PIN_RESET);
	TIM3->CCR4 = 0;
	TIM3->CCR3 = 0;
	move_el = 0;
}

void MYPROG_SendData(const char * data, int size)
{
	 HAL_UART_Transmit(&huart1, (uint8_t *) data, size, 1000);
}

void MYPROG_GetData(char *buffer, int size)
{

}

void MYPROG_SendAcknowledgement(const char *command, bool accepted, const char *reason)
{
	char acknowledgement[64];
	int acknowledgement_length;
	if (accepted)
	{
		acknowledgement_length = snprintf(acknowledgement, sizeof(acknowledgement),
			"MSG:ACK:%s;\r\n", command);
	}
	else
	{
		acknowledgement_length = snprintf(acknowledgement, sizeof(acknowledgement),
			"MSG:NAK:%s,%s;\r\n", command, reason);
	}
	if (acknowledgement_length > 0 && acknowledgement_length < (int)sizeof(acknowledgement))
	{
		MYPROG_SendData(acknowledgement, acknowledgement_length);
	}
}

bool counter_change_exceeds(uint32_t current, uint32_t previous, uint32_t maximum_change)
{
	uint32_t change = current >= previous ? current - previous : previous - current;
	return change > maximum_change;
}

void MYPROG_main_loop()
{
	float settimer1 =0;
	float settimer2 =0;
	char sendbuffer[64];
	// Private command copy used by the main loop after releasing the shared UART buffer.
	char command_to_process[sizeof(rxBuffer_command)];
	// True only when command_to_process contains a command to parse during this loop.
	bool command_available = false;
	bool oversized_command_available = false;
	bool rejected_frame_available = false;
	bool unable_to_parse_frame_available = false;
	bool emergency_stop_ack_available = false;
	bool position_discontinuity_detected = false;
	// Snapshot used to detect an emergency stop received after the command was copied.
	// Example: if this is 4 and stop_generation becomes 5, the copied command is cancelled.
	uint32_t copied_stop_generation = 0;



	Az_pos = TIM2->CNT;
	El_pos = TIM1->CNT;

	if (position_discontinuity_baseline_valid && move &&
		(counter_change_exceeds((uint32_t)Az_pos, previous_azimuth_counter, MAX_POSITION_CHANGE_COUNTS) ||
		 counter_change_exceeds((uint32_t)El_pos, previous_elevation_counter, MAX_POSITION_CHANGE_COUNTS)))
	{
		move = 0;
		mode = 0;
		MYPROG_disable_az();
		MYPROG_disable_el();
		position_discontinuity_detected = true;
	}
	previous_azimuth_counter = (uint32_t)Az_pos;
	previous_elevation_counter = (uint32_t)El_pos;
	position_discontinuity_baseline_valid = true;

	Az_pos_deg = (Az_pos - 43200)/240.0;
	El_pos_deg = (El_pos - 21600)/240.0;

	MYPROG_Delay(5);
	//MYPROG_SendData("ACK\n",3);

	// Briefly pause UART interrupts while copying the shared command buffer.
	// Example: the ISR can now receive the next frame while this private copy is parsed.
	__disable_irq();
	if (command_read == 1)
	{
		memcpy(command_to_process, rxBuffer_command, sizeof(command_to_process));
		command_read = 0;
		copied_stop_generation = stop_generation;
		command_available = true;
	}
	else if (command_read == -1)
	{
		command_read = 0;
		oversized_command_available = true;
	}
	if (rejected_frame_count > 0)
	{
		rejected_frame_count--;
		rejected_frame_available = true;
	}
	if (unable_to_parse_frame_count > 0)
	{
		unable_to_parse_frame_count--;
		unable_to_parse_frame_available = true;
	}
	if (emergency_stop_ack_count > 0)
	{
		emergency_stop_ack_count--;
		emergency_stop_ack_available = true;
	}
	__enable_irq();

	if (oversized_command_available)
	{
		MYPROG_SendAcknowledgement("UNKNOWN", false, "UNABLE_TO_PARSE");
	}
	if (emergency_stop_ack_available)
	{
		MYPROG_SendAcknowledgement("EMERGENCY_STOP", true, NULL);
	}
	if (rejected_frame_available)
	{
		MYPROG_SendAcknowledgement("UNKNOWN", false, "REJECTED");
	}
	if (unable_to_parse_frame_available)
	{
		MYPROG_SendAcknowledgement("UNKNOWN", false, "UNABLE_TO_PARSE");
	}

	if(command_available)
	{
		//MYPROG_SendData("read command",10);
		// Keep parsed movement coordinates local until the complete command can be applied safely.
		float move_yaw = 0.0f;
		float move_pitch = 0.0f;
    uint32_t azimuth_counter = 0;
    uint32_t elevation_counter = 0;
		command_type_t command_type = identify_command_type(command_to_process);
		bool command_parsed = false;
		bool command_rejected = false;
		switch (command_type)
		{
		case COMMAND_MOV:
			command_parsed = parse_mov_command(command_to_process, &move_yaw, &move_pitch);
			command_rejected = command_parsed &&
				(move_yaw < MIN_PAN_DEG || move_yaw > MAX_PAN_DEG ||
				 move_pitch < MIN_MOVE_TILT_DEG || move_pitch > MAX_MOVE_TILT_DEG);
			break;
		case COMMAND_SET:
			command_parsed = parse_set_command(command_to_process, &settimer1, &settimer2);
			command_rejected = command_parsed &&
				(settimer1 < MIN_PAN_DEG || settimer1 > MAX_PAN_DEG ||
				 settimer2 < MIN_SET_TILT_DEG || settimer2 > MAX_SET_TILT_DEG);
			break;
		case COMMAND_VERSION:
			command_parsed = strcmp(command_to_process, "CMD:VERSION") == 0;
			break;
		case COMMAND_CNT:
			command_parsed = strcmp(command_to_process, "CMD:CNT") == 0;
			break;
		case COMMAND_MOV_CNT:
			command_parsed = parse_counter_command(command_to_process, "CMD:MOV_CNT:PAN=",
				&azimuth_counter, &elevation_counter);
			break;
		case COMMAND_SET_CNT:
			command_parsed = parse_counter_command(command_to_process, "CMD:SET_CNT:PAN=",
				&azimuth_counter, &elevation_counter);
			break;
		default:
			break;
		}
		// Set when an emergency stop invalidates the command while it is being parsed.
		bool command_cancelled = false;
		bool send_counter_response = false;

		// Parsing happens with interrupts enabled. Pause them again only while applying
		// the result, and first make sure p was not received during parsing.
		__disable_irq();
		if (copied_stop_generation != stop_generation)
		{
			command_cancelled = true;
		}
		else if (!command_parsed || command_rejected)
		{
			move = 0;
			mode = 0;
			MYPROG_disable_az();
			MYPROG_disable_el();
		}
		else
		{
			switch (command_type)
			{
			case COMMAND_CNT:
				azimuth_counter = TIM2->CNT;
				elevation_counter = TIM1->CNT;
				send_counter_response = true;
				break;
			case COMMAND_SET_CNT:
				move = 0;
				mode = 0;
				MYPROG_disable_az();
				MYPROG_disable_el();
				TIM2->CNT = azimuth_counter;
				TIM1->CNT = elevation_counter;
				azimuth_counter = TIM2->CNT;
				elevation_counter = TIM1->CNT;
				previous_azimuth_counter = azimuth_counter;
				previous_elevation_counter = elevation_counter;
				position_discontinuity_baseline_valid = true;
				send_counter_response = true;
				break;
			case COMMAND_MOV_CNT:
				move_yaw = ((float)azimuth_counter - 43200.0f) / 240.0f;
				move_pitch = ((float)elevation_counter - 21600.0f) / 240.0f;
				/* fall through */
			case COMMAND_MOV:
				Azc = move_yaw;
				Elc = move_pitch;
				move = 1;
				mode = 0;
				command_position_AZ = Azc;
				command_position_EL = Elc;
				Az_speed = 255;
				El_speed = 255;
				break;
			case COMMAND_SET:
			{
				move = 0;
				mode = 0;
				TIM1->CNT = (uint32_t)(21600 + (settimer2 * 240.0f));
				TIM2->CNT = (uint32_t)(43200 + (settimer1 * 240.0f));
				previous_azimuth_counter = TIM2->CNT;
				previous_elevation_counter = TIM1->CNT;
				position_discontinuity_baseline_valid = true;
				break;
			}
			default:
				break;
			}
		}
		__enable_irq();

		bool command_accepted = !command_cancelled && command_parsed && !command_rejected;
		if (command_accepted)
		{
			MYPROG_SendAcknowledgement(command_type_name(command_type), true, NULL);
		}
		else
		{
			const char *reason = command_rejected
				? "OUT_OF_BOUNDS"
				: (command_cancelled ? "REJECTED" : "UNABLE_TO_PARSE");
			MYPROG_SendAcknowledgement(command_type_name(command_type), false, reason);
		}

		if (command_accepted && send_counter_response)
		{
			int counter_message_length = snprintf(sendbuffer, sizeof(sendbuffer),
				"MSG:CNT:PAN=%lu,TILT=%lu;\r\n",
				(unsigned long)azimuth_counter,(unsigned long)elevation_counter);
			if (counter_message_length > 0 && counter_message_length < (int)sizeof(sendbuffer))
			{
				MYPROG_SendData(sendbuffer, counter_message_length);
			}
		}
		else if (command_accepted && command_type == COMMAND_VERSION)
		{
			MYPROG_SendData(firmware_version_message, (int)sizeof(firmware_version_message) - 1);
		}
		else if (command_accepted && (command_type == COMMAND_MOV || command_type == COMMAND_MOV_CNT || command_type == COMMAND_SET))
		{
			// snprintf returns the message length without counting the final null byte.
			int command_message_length = snprintf(sendbuffer, sizeof(sendbuffer), "%.2f , %.2f \r\n", Azc, Elc);
			// A length as large as the buffer means snprintf had to truncate the message.
			if (command_message_length > 0 && command_message_length < (int)sizeof(sendbuffer))
			{
				MYPROG_SendData(sendbuffer, command_message_length);
			}
		}
	}

	if (position_discontinuity_detected)
	{
		// A command received in the same loop must not restart motion after the fault.
		move = 0;
		mode = 0;
		MYPROG_disable_az();
		MYPROG_disable_el();
		MYPROG_SendData(position_discontinuity_message, (int)sizeof(position_discontinuity_message) - 1);
	}

	int target_reached = move_az && move_el;

	if(move && !target_reached && mode ==0)
			{
			MYPROG_motor_control_loop();
			}else if ( mode == 1)
			{
				move = 0;
			}else
			{
				//command_read =0;
					  move = 0;
					  //buff =0;
					  MYPROG_disable_az();
					  MYPROG_disable_el();
			}



	// Example: send through the report's \n, but not the unused remainder of sendbuffer.
	int position_message_length = snprintf(sendbuffer, sizeof(sendbuffer), "MSG:POS:PAN=%.3f,TILT=%.3f\r\n", Az_pos_deg, El_pos_deg);
	if (position_message_length > 0 && position_message_length < (int)sizeof(sendbuffer))
	{
		MYPROG_SendData(sendbuffer, position_message_length);
	}


	//MYPROG_SendData(rxBuffer_command,64);




	//MYPROG_move_axis(1, 128,1);
	//MYPROG_move_axis(2, 128,1);

}

void MYPROG_move_axis(int axis, int speed, int dir)
{
	// ch1 is AZ clockwise   ch2 is AZ counter clockwise
	// ch3 is EL clockwise   ch4 is EL counter clockwise
	//speed is PWM from 0 to 255;

	    if(axis ==1){
	    	MYPROG_disable_az();
	    	if(dir ==1){
	    	TIM3->CCR2 = 0;
	    	TIM3->CCR1 = speed;
	    	MYPROG_enable_az();
	    	}else{
	    	TIM3->CCR1 = 0;
	    	TIM3->CCR2 = speed;
	    	MYPROG_enable_az();
	    	}

	    }else if(axis ==2)
	    {
	    	MYPROG_disable_el();
	    	if(dir ==1){

	    	TIM3->CCR3 = speed;
	    	TIM3->CCR4 = 0;
	    	MYPROG_enable_el();
	    	}else{
	    	TIM3->CCR4 = speed;
	    	TIM3->CCR3 = 0;
	    	MYPROG_enable_el();
	    	}


	    }else{
	    	MYPROG_disable_el();
	    	MYPROG_disable_az();
	    	TIM3->CCR2 =0;
	    	TIM3->CCR1 =0;
	    	TIM3->CCR3 =0;
	    	TIM3->CCR4 =0;
	    }
}

void MYPROG_motor_control_loop()
{

	float devEl = fabs(El_pos_deg - command_position_EL);
	float devAz = fabs(Az_pos_deg - command_position_AZ);



	if(Az_pos_deg > (command_position_AZ-2) && Az_pos_deg < (command_position_AZ+2))
		{
			//set low speed
			Az_speed =devAz*78+99;
		}else {
			//set slew speed
			Az_speed = 255;
		}


	if(El_pos_deg > (command_position_EL-2) && El_pos_deg < (command_position_EL+2))
			{
				//set low speed
				El_speed = devEl*96+63;
			}else {
				//set slew speed
				El_speed = 255;
			}






	if(Az_pos_deg < (command_position_AZ-0.1))
	{
		//move right
		MYPROG_move_axis(1, Az_speed, 1);
		move_az = 0;
	}else if( Az_pos_deg>(command_position_AZ+0.1))
	{
		// move left
		MYPROG_move_axis(1, Az_speed, 0);
		move_az = 0;
	}else{
		//stop
		MYPROG_disable_az();
		move_az = 1;
	}




	if(El_pos_deg < (command_position_EL-0.1))
	{
		//move right
		MYPROG_move_axis(2, El_speed, 1);
		move_el =0;
	}else if( El_pos_deg>(command_position_EL+0.1))
	{
		// move left
		MYPROG_move_axis(2, El_speed, 0);
		move_el =0;
	}else{
		//stop
		 MYPROG_disable_el();
		 move_el =1;
	}








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
  	 TIM3->CCR2 =0;
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_2);
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_3);
    HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_4);

    HAL_UART_Receive_IT(&huart1, &buff, 1);
    HAL_TIM_Encoder_Start(&htim2, TIM_CHANNEL_ALL);
    HAL_TIM_Encoder_Start(&htim1, TIM_CHANNEL_ALL);

    MYPROG_disable_el();
    MYPROG_disable_az();
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */

	  MYPROG_main_loop();

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
  htim1.Init.Period = 43200;
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
