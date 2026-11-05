#include <unity.h>
#include "../test_main/fakes/hw_fakes.c"
#include "screen_renderer.h"
#include "voice_diagnostics.h"
void setUp(void) {}
void tearDown(void) {}
static uint16_t guarded[32402];
static void bounds_and_layouts(void) {
 for(int wide=0;wide<2;wide++) for(int state=0;state<6;state++) {
  guarded[0]=0xdead;guarded[32401]=0xbeef;
  screen_render_model_t m={.view=screen_ui_view(state),.state=state,.wifi=true,.battery_percent=100,.backend_status=200,.device_id="ID 70041ddc4aac",.wake_status=1};
  m.timer=screen_ui_recording_timer(0,119000,120);
  TEST_ASSERT_TRUE(screen_render(guarded+1,wide?240:135,wide?135:240,&m));
  TEST_ASSERT_EQUAL_HEX16(0xdead,guarded[0]);TEST_ASSERT_EQUAL_HEX16(0xbeef,guarded[32401]);
 }
}
static void long_message_and_setup(void) {
 for(int wide=0;wide<2;wide++) {
  screen_render_model_t m={.view={"ОШИБКА","ОШИБКА ПОДКЛЮЧЕНИЯ\nНАЖМИТЕ ДЛЯ СБРОСА",0xf800,SCREEN_ICON_ERROR},.state=STATE_ERROR,.device_id="ID 70041ddc4aac"};
  TEST_ASSERT_TRUE(screen_render(guarded+1,wide?240:135,wide?135:240,&m));
  m.setup=true;m.ssid="Zateya-4AAC";
  TEST_ASSERT_TRUE(screen_render(guarded+1,wide?240:135,wide?135:240,&m));
  int w=wide?240:135,left=wide?5:12,top=wide?12:36;
  /* All four sides of the four-module quiet zone must remain white. */
  for(int i=0;i<111;i++)for(int q=0;q<12;q++) {
   TEST_ASSERT_EQUAL_HEX16(0xffff,guarded[1+(top+q)*w+left+i]);
   TEST_ASSERT_EQUAL_HEX16(0xffff,guarded[1+(top+110-q)*w+left+i]);
   TEST_ASSERT_EQUAL_HEX16(0xffff,guarded[1+(top+i)*w+left+q]);
   TEST_ASSERT_EQUAL_HEX16(0xffff,guarded[1+(top+i)*w+left+110-q]);
  }
 }
}
static void all_copy(void) {
 const char *hints[]={"СКАЖИТЕ ЗАТЕЯ\nИЛИ КНОПКА","ДОЖДИТЕСЬ РЕПЛИКИ","ГОВОРИТЕ","ОТПРАВЛЯЮ\nДИАГНОСТИКУ","ПРОШИВКА 100%\nНЕ ВЫКЛЮЧАЙТЕ","ПОСЛЕ ОБНОВЛЕНИЯ"};
 for(int wide=0;wide<2;wide++) {
  screen_render_model_t m={.view=screen_ui_view(STATE_ERROR),.state=STATE_ERROR,.device_id="ID 70041ddc4aac"};
  for(int code=0;code<30;code++) {
   m.view.hint=voice_diag_error_hint(code);
   TEST_ASSERT_TRUE(screen_render(guarded+1,wide?240:135,wide?135:240,&m));
  }
  for(unsigned n=0;n<sizeof(hints)/sizeof(hints[0]);n++) {
   m.view.hint=hints[n];
   TEST_ASSERT_TRUE(screen_render(guarded+1,wide?240:135,wide?135:240,&m));
  }
  for(int phase=0;phase<3;phase++) {
   m.view=screen_ui_view_with_phase(STATE_PROCESSING,phase);
   TEST_ASSERT_TRUE(screen_render(guarded+1,wide?240:135,wide?135:240,&m));
  }
 }
}
int main(void) {UNITY_BEGIN();RUN_TEST(bounds_and_layouts);RUN_TEST(long_message_and_setup);RUN_TEST(all_copy);return UNITY_END();}
