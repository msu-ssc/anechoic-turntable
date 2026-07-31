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
#include "globalvars.h"
#include <string.h>
#include <stdio.h>
#include <stdbool.h>
#include <math.h>
#include "firmware_version.h"

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
char rxBuffer_command[64];
int buffn =0;
int command_read =0;
uint8_t buff;

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
	  command_read =0;
	  move = 0;
	  mode = 0;
	  buff =0;
	  MYPROG_disable_az();
	  MYPROG_disable_el();
  }else
  {

  if(buff != ';')
  {
	  rxBuffer[buffn] = buff;
  	  command_read =0;
  	  buffn ++;
  	  buff =0;
  }else if(buff == ';')
  {	  memcpy(rxBuffer_command,rxBuffer,buffn);
    rxBuffer_command[buffn] = '\0';
	  command_read =1;
	  buffn =0;
	  memset(rxBuffer, 0, sizeof(rxBuffer));
	  buff = 0;
  }

  if(buffn>64)
  {
	  buffn=0;
	  memset(rxBuffer, 0, sizeof(rxBuffer));
	  command_read = -1;
	  buff = 0;

  }

  }
  buff = 0;
  HAL_UART_Receive_IT(&huart1, &buff, 1);


}

// Function to determine if a user has input in the info command
bool parse_info_command(const char *input)
{
  return strcmp(input, "CMD:INFO") == 0;
}

// Function to parse the input string and extract two float values
bool parse_mov_command(const char *input, float *x, float *y) {
    // Buffer to hold the part of the string with the numbers
    char coordinates[20];
    // Find the portion of the string after "CMD:MOV:"
    const char *start = strstr(input, "CMD:MOV:");
    if (start != NULL) {
        // Move the pointer past "CMD:MOV:"
        start += strlen("CMD:MOV:");
        // Copy the coordinates (before the semicolon)
        strncpy(coordinates, start, strlen(start) - 1);
        coordinates[strlen(start) - 1] = '\0';  // Null-terminate the string
        // Use sscanf to parse the two float numbers
        if (sscanf(coordinates, "%f,%f", x, y) == 2) {
            return true;  // Parsing successful
        }
    }
    return false;  // Invalid format
}

bool parse_set_command(const char *input, float *x, float *y) {
    // Buffer to hold the part of the string with the numbers
    char coordinates[20];
    // Find the portion of the string after "CMD:MOV:"
    const char *start = strstr(input, "CMD:SET:");
    if (start != NULL) {
        // Move the pointer past "CMD:MOV:"
        start += strlen("CMD:SET:");
        // Copy the coordinates (before the semicolon)
        strncpy(coordinates, start, strlen(start) - 1);
        coordinates[strlen(start) - 1] = '\0';  // Null-terminate the string
        // Use sscanf to parse the two float numbers
        if (sscanf(coordinates, "%f,%f", x, y) == 2) {
            return true;  // Parsing successful
        }
    }
    return false;  // Invalid format
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

void MYPROG_SendData(char * data, int size)
{
	 HAL_UART_Transmit(&huart1, (uint8_t *) data, size, 1000);
}

void MYPROG_GetData(char *buffer, int size)
{

}

void MYPROG_main_loop()
{
	float settimer1 =0;
	float settimer2 =0;
	char sendbuffer[42];



	Az_pos = TIM2->CNT;
	El_pos = TIM1->CNT;

	Az_pos_deg = (Az_pos - 43200)/240.0;
	El_pos_deg = (El_pos - 21600)/240.0;

	MYPROG_Delay(5);
	//MYPROG_SendData("ACK\n",3);

	if (command_read == 1)
{
    if (parse_info_command(rxBuffer_command))
    {
        static const char firmware_info[] =
            "FIRMWARE VERSION: " FIRMWARE_VERSION "\r\n";

        MYPROG_SendData(
            (char *)firmware_info,
            sizeof(firmware_info) - 1
        );
    }
    else
    {
        if (parse_mov_command(rxBuffer_command, &Azc, &Elc))
        {
            move = 1;
            mode = 0;
        }
        else
        {
            move = 0;
        }

        if (parse_set_command(
                rxBuffer_command,
                &settimer1,
                &settimer2))
        {
            TIM1->CNT =
                (uint32_t)(21600 + (settimer2 * 240.0f));
            TIM2->CNT =
                (uint32_t)(43200 + (settimer1 * 240.0f));
        }

        snprintf(
            sendbuffer,
            sizeof(sendbuffer),
            "%.2f , %.2f \r\n",
            Azc,
            Elc
        );
        MYPROG_SendData(sendbuffer, strlen(sendbuffer));

        command_position_AZ = Azc;
        command_position_EL = Elc;
        Az_speed = 255;
        El_speed = 255;
    }

    command_read = 0;
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



	snprintf(sendbuffer,42,"Pos= El: %.2f , Az: %.2f \r\n",El_pos_deg,Az_pos_deg);
	MYPROG_SendData(sendbuffer,42);


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
