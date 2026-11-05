#ifdef ESP_PLATFORM
#include "board_orientation.h"
#include "board_sticks3.h"
#include "vendor/bmi270/bmi270.h"
#include "driver/i2c_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_rom_sys.h"
#include "esp_log.h"
#include <stdatomic.h>
#include <string.h>
static atomic_int rotation;
static i2c_master_dev_handle_t sensor;
static struct bmi2_dev dev;
static int8_t read_reg(uint8_t reg,uint8_t *data,uint32_t len,void *unused) {
 (void)unused;return i2c_master_transmit_receive(sensor,&reg,1,data,len,20)==ESP_OK?0:-1;
}
static int8_t write_reg(uint8_t reg,const uint8_t *data,uint32_t len,void *unused) {
 (void)unused;uint8_t bytes[33];if(len>32)return -1;bytes[0]=reg;memcpy(bytes+1,data,len);
 return i2c_master_transmit(sensor,bytes,len+1,20)==ESP_OK?0:-1;
}
static void delay_us(uint32_t us,void *unused) {
 (void)unused;if(us>=1000)vTaskDelay(pdMS_TO_TICKS(us/1000)+1);else esp_rom_delay_us(us);
}
static void task(void *unused) {
 (void)unused;
 /* Full Bosch initialization uploads and checks the required 8 KiB config. */
 dev=(struct bmi2_dev){.intf=BMI2_I2C_INTF,.read=read_reg,.write=write_reg,.delay_us=delay_us,.read_write_len=32};
 int8_t result=bmi270_init(&dev);
 struct bmi2_sens_config config={.type=BMI2_ACCEL};
 if(!result) result=bmi270_get_sensor_config(&config,1,&dev);
 config.cfg.acc.odr=BMI2_ACC_ODR_25HZ;config.cfg.acc.range=BMI2_ACC_RANGE_2G;
 config.cfg.acc.bwp=BMI2_ACC_NORMAL_AVG4;config.cfg.acc.filter_perf=BMI2_PERF_OPT_MODE;
 if(!result)result=bmi270_set_sensor_config(&config,1,&dev);
 uint8_t accel=BMI2_ACCEL,gyro=BMI2_GYRO;
 if(!result) result=bmi270_sensor_disable(&gyro,1,&dev);
 if(!result) result=bmi270_sensor_enable(&accel,1,&dev);
 if(result) {ESP_LOGW("orientation","BMI270 unavailable (%d); keeping portrait",result);vTaskDelete(NULL);return;}
 screen_orientation_t policy={0};
 for(;;) {
  struct bmi2_sens_data data={0};
  bool valid=bmi2_get_sensor_data(&data,&dev)==BMI2_OK;
  screen_orientation_sample_sticks3(&policy,data.acc.x/16384.0f,data.acc.y/16384.0f,data.acc.z/16384.0f,valid,(uint32_t)(esp_timer_get_time()/1000));
  atomic_store(&rotation,policy.rotation);
  vTaskDelay(pdMS_TO_TICKS(100));
 }
}
void board_orientation_start(void) {
 static bool started;if(started)return;started=true;
 /* Called after the power driver creates the shared bus, on the display owner. */
 i2c_master_bus_handle_t bus=board_sticks3_i2c_bus();if(!bus)return;
 i2c_device_config_t cfg={.dev_addr_length=I2C_ADDR_BIT_LEN_7,.device_address=0x68,.scl_speed_hz=400000};
 if(i2c_master_bus_add_device(bus,&cfg,&sensor)!=ESP_OK)return;
 if(xTaskCreate(task,"orientation",4096,NULL,2,NULL)!=pdPASS) {
  i2c_master_bus_rm_device(sensor);sensor=NULL;
 }
}
screen_rotation_t board_orientation_get(void) {return (screen_rotation_t)atomic_load(&rotation);}
#endif
