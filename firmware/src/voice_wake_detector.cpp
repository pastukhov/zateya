#include "voice_wake_detector.h"
#ifdef ESP_PLATFORM
#include <atomic>
#include <cstring>
#include <algorithm>
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_resource_variable.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "frontend.h"
#include "frontend_util.h"
#include "voice_wake_model_data.h"
#include "voice_wake_score.h"

namespace {
struct Frame { unsigned epoch; int16_t samples[160]; };
QueueHandle_t queue;
StaticQueue_t queue_control;
uint8_t *queue_storage;
std::atomic<bool> ready{false};
std::atomic<unsigned> epoch{1}, detection_epoch{0};
uint8_t pending[320]; size_t pending_size;
void worker(void *) {
 tflite::MicroMutableOpResolver<13> ops;
 bool ok=ops.AddCallOnce()==kTfLiteOk && ops.AddVarHandle()==kTfLiteOk &&
 ops.AddReshape()==kTfLiteOk && ops.AddReadVariable()==kTfLiteOk &&
 ops.AddConcatenation()==kTfLiteOk && ops.AddStridedSlice()==kTfLiteOk &&
 ops.AddAssignVariable()==kTfLiteOk && ops.AddConv2D()==kTfLiteOk &&
 ops.AddDepthwiseConv2D()==kTfLiteOk && ops.AddSplitV()==kTfLiteOk &&
 ops.AddFullyConnected()==kTfLiteOk && ops.AddLogistic()==kTfLiteOk && ops.AddQuantize()==kTfLiteOk;
 const tflite::Model *model=tflite::GetModel(zateya_model);
 uint8_t *arena=(uint8_t*)heap_caps_aligned_alloc(16,32000,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 uint8_t *vars=(uint8_t*)heap_caps_aligned_alloc(16,4096,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!ok || model->version()!=TFLITE_SCHEMA_VERSION || !arena || !vars) {
  free(arena);free(vars);ESP_LOGE("wake","Model allocation/schema failed");vTaskDelete(nullptr);return;
 }
 auto *allocator=tflite::MicroAllocator::Create(vars,4096);
 auto *variables=tflite::MicroResourceVariables::Create(allocator,20);
 tflite::MicroInterpreter interpreter(model,ops,arena,32000,variables);
 if(interpreter.AllocateTensors()!=kTfLiteOk) {
  ESP_LOGE("wake","AllocateTensors failed");vTaskDelete(nullptr);return;
 }
 TfLiteTensor *input=interpreter.input(0), *output=interpreter.output(0);
 if(input->type!=kTfLiteInt8 || input->dims->size!=3 || input->dims->data[0]!=1 ||
    input->dims->data[1]!=3 || input->dims->data[2]!=40 || output->type!=kTfLiteUInt8 || output->bytes!=1) {
  ESP_LOGE("wake","Unsupported tensor contract");vTaskDelete(nullptr);return;
 }
 FrontendConfig config={};FrontendState frontend={};
 config.window.size_ms=30;config.window.step_size_ms=10;
 config.filterbank.num_channels=40;config.filterbank.lower_band_limit=125;config.filterbank.upper_band_limit=7500;
 config.noise_reduction.smoothing_bits=10;config.noise_reduction.even_smoothing=0.025;
 config.noise_reduction.odd_smoothing=0.06;config.noise_reduction.min_signal_remaining=0.05;
 config.pcan_gain_control.enable_pcan=1;config.pcan_gain_control.strength=0.95;
 config.pcan_gain_control.offset=80;config.pcan_gain_control.gain_bits=21;
 config.log_scale.enable_log=1;config.log_scale.scale_shift=6;
 if(!FrontendPopulateState(&config,&frontend,16000)) {ESP_LOGE("wake","Frontend failed");vTaskDelete(nullptr);return;}
 voice_wake_score_t score={};unsigned active_epoch=0,stride=0;unsigned max_us=0;
 ready.store(true);ESP_LOGI("wake","Model ready: 60840 bytes, arena=%u, input=1x3x40",(unsigned)interpreter.arena_used_bytes());
 Frame frame;
 for(;;) {
  if(xQueueReceive(queue,&frame,portMAX_DELAY)!=pdTRUE)continue;
  if(frame.epoch!=epoch.load())continue;
  if(frame.epoch!=active_epoch) {
   active_epoch=frame.epoch;stride=0;voice_wake_score_reset(&score);FrontendReset(&frontend);
   if(interpreter.Reset()!=kTfLiteOk)break;
  }
  size_t offset=0;
  while(offset<160) {
   size_t consumed=0;auto features=FrontendProcessSamples(&frontend,frame.samples+offset,160-offset,&consumed);
   if(!consumed)break;
   offset+=consumed;
   if(!features.size)continue;
   if(features.size!=40){ready.store(false);break;}
   for(unsigned i=0;i<40;i++) {
    int value=((features.values[i]*256+333)/666)-128;
    input->data.int8[stride*40+i]=(int8_t)std::min(127,std::max(-128,value));
   }
   if(++stride<3)continue;
   stride=0;int64_t start=esp_timer_get_time();
   if(interpreter.Invoke()!=kTfLiteOk){ready.store(false);break;}
   max_us=std::max(max_us,(unsigned)(esp_timer_get_time()-start));
   if(voice_wake_score_feed(&score,output->data.uint8[0])) {
    if(active_epoch==epoch.load())detection_epoch.store(active_epoch);
    ESP_LOGI("wake","Detected Zateya; inference max=%u us",max_us);voice_wake_score_reset(&score);
   }
  }
  if(!ready.load())break;
 }
 ready.store(false);ESP_LOGE("wake","Inference stopped; button remains available");vTaskDelete(nullptr);
}
}
bool voice_wake_detector_start(void) {
 if(queue)return false;
 queue_storage=(uint8_t*)heap_caps_malloc(32*sizeof(Frame),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!queue_storage)return false;
 queue=xQueueCreateStatic(32,sizeof(Frame),queue_storage,&queue_control);
 if(!queue){free(queue_storage);queue_storage=nullptr;return false;}
 if(xTaskCreate(worker,"wake_inference",12288,nullptr,3,nullptr)==pdPASS)return true;
 vQueueDelete(queue);queue=nullptr;free(queue_storage);queue_storage=nullptr;return false;
}
bool voice_wake_detector_ready(void){return ready.load();}
void voice_wake_detector_reset(void){pending_size=0;epoch.fetch_add(1);detection_epoch.store(0);if(queue)xQueueReset(queue);}
void voice_wake_detector_feed(const uint8_t *pcm,size_t bytes) {
 if(!ready.load())return;
 while(bytes) {
  size_t n=std::min(bytes,sizeof(pending)-pending_size);memcpy(pending+pending_size,pcm,n);pending_size+=n;pcm+=n;bytes-=n;
  if(pending_size==sizeof(pending)) {
   Frame f;f.epoch=epoch.load();memcpy(f.samples,pending,sizeof(pending));pending_size=0;
   if(xQueueSend(queue,&f,0)!=pdTRUE){voice_wake_detector_reset();ESP_LOGW("wake","Audio queue overflow; detector reset");return;}
  }
 }
}
bool voice_wake_detector_detected(void){unsigned value=detection_epoch.exchange(0);return value && value==epoch.load();}
#else
bool voice_wake_detector_start(void){return false;}
bool voice_wake_detector_ready(void){return false;}
void voice_wake_detector_reset(void){}
void voice_wake_detector_feed(const uint8_t*p,size_t n){(void)p;(void)n;}
bool voice_wake_detector_detected(void){return false;}
#endif
