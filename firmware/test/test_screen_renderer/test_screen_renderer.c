#include <unity.h>
#include "../test_main/fakes/hw_fakes.c"
#include "screen_renderer.h"
#include "voice_diagnostics.h"
#include "screen_font.h"
#include <string.h>
void setUp(void) {}
void tearDown(void) {}
static uint16_t guarded[32402];
static uint16_t expected[32400];
static void button_left_guidance_is_readable(void) {
 for(int hold=0;hold<2;hold++) {
  screen_render_model_t m={.view=screen_ui_view(STATE_IDLE),.state=STATE_IDLE,
   .hold_mode=hold,.rotation=SCREEN_ROTATION_270};
  TEST_ASSERT_TRUE(screen_render(guarded+1,240,135,&m));
  for(int i=0;i<32400;i++)expected[i]=0x0083;
  TEST_ASSERT_TRUE(screen_font_draw_centered(expected,240,135,49,64,SCREEN_FONT_SMALL,hold?"ДЕРЖИТЕ":"КНОПКА:",0x74B3));
  TEST_ASSERT_TRUE(screen_font_draw_centered(expected,240,135,49,79,SCREEN_FONT_SMALL,hold?"КНОПКУ":"СТАРТ / СТОП",0x74B3));
  for(int y=63;y<98;y++)for(int x=0;x<97;x++)
   TEST_ASSERT_EQUAL_HEX16(expected[y*240+x],guarded[1+y*240+x]);
 }
}
static void landscape_columns_move_without_reflection(void) {
 const screen_ui_view_t overrides[]={
  {"ОБНОВЛЯЮ","ПРОШИВКА 73%\nНЕ ВЫКЛЮЧАЙТЕ",0x07e0,SCREEN_ICON_THINKING},
  {"ОТЧЁТ","ОТПРАВЛЯЮ\nДИАГНОСТИКУ",0xF5A8,SCREEN_ICON_THINKING},
  {"СЕРВЕР","НЕТ СВЯЗИ",0xF5A8,SCREEN_ICON_THINKING},
  {"СЛУШАЮ","ГОВОРИТЕ",0x07e0,SCREEN_ICON_THINKING},
  {"ПРОВЕРЯЮ","ПОСЛЕ ОБНОВЛЕНИЯ",0xF5A8,SCREEN_ICON_THINKING},
 };
 for(int scene=0;scene<17;scene++) {
  screen_render_model_t m={.state=scene<6?scene:STATE_IDLE,.phase=12,
   .wifi=true,.usb=true,.charging=true,.battery_percent=83,.backend_status=200,
   .device_id="ID 70041ddc4aac",.hold_mode=scene&1};
  m.view=screen_ui_view(m.state);
  m.timer=screen_ui_recording_timer(0,scene==STATE_RECORDING?119000:93000,120);
  if(scene==6 || scene==7) {m.wake_status=1;m.view.hint="СКАЖИТЕ ЗАТЕЯ\nИЛИ КНОПКА";}
  if(scene>=8 && scene<13)m.view=overrides[scene-8];
  if(scene>=13) {
   m.state=STATE_RECORDING;m.view=screen_ui_view(m.state);
   m.timer=screen_ui_recording_timer(0,scene==13?0:scene==14?111000:116000,120);
   m.phase=scene==16?9:0; /* Both blink colors of the final warning. */
  }
  TEST_ASSERT_TRUE(screen_render(expected,240,135,&m)); /* Legacy zero model. */
  m.rotation=SCREEN_ROTATION_90;
  TEST_ASSERT_TRUE(screen_render(guarded+1,240,135,&m));
  TEST_ASSERT_EQUAL_MEMORY(expected,guarded+1,sizeof(expected));
  guarded[0]=0xdead;guarded[32401]=0xbeef;
  m.rotation=SCREEN_ROTATION_270;
  TEST_ASSERT_TRUE(screen_render(guarded+1,240,135,&m));
  TEST_ASSERT_EQUAL_HEX16(0xdead,guarded[0]);TEST_ASSERT_EQUAL_HEX16(0xbeef,guarded[32401]);
  for(int y=0;y<135;y++) {
   /* Intact state [0,141] moves right; intact indicators [143,239] move left. */
   TEST_ASSERT_EQUAL_MEMORY(expected+y*240,guarded+1+y*240+98,142*sizeof(uint16_t));
   TEST_ASSERT_EQUAL_MEMORY(expected+y*240+143,guarded+1+y*240,97*sizeof(uint16_t));
   TEST_ASSERT_EQUAL_HEX16(expected[y*240+142],guarded[1+y*240+97]);
  }
 }
}
static void rotation_preserves_portrait_and_setup(void) {
 for(int r=0;r<4;r++)for(int setup=0;setup<2;setup++) {
  screen_render_model_t m={.state=STATE_IDLE,.view=screen_ui_view(STATE_IDLE),
   .setup=setup,.ssid="Zateya-4AAC",.device_id="ID 70041ddc4aac"};
  int w=screen_orientation_width(r),h=screen_orientation_height(r);
  TEST_ASSERT_TRUE(screen_render(expected,w,h,&m));
  m.rotation=r;
  TEST_ASSERT_TRUE(screen_render(guarded+1,w,h,&m));
  if(setup || !(r&1))TEST_ASSERT_EQUAL_MEMORY(expected,guarded+1,sizeof(expected));
 }
}
static void ready_landscape(bool hold,unsigned wake) {
 screen_render_model_t m={.view=screen_ui_view(STATE_IDLE),.state=STATE_IDLE,.wifi=true,.usb=true,.battery_percent=83,.backend_status=200,.device_id="ID 70041ddc4aac",.hold_mode=hold,.wake_status=wake};
 if(wake)m.view.hint="СКАЖИТЕ ЗАТЕЯ\nИЛИ КНОПКА"; /* Actual board input. */
 TEST_ASSERT_TRUE(screen_render(guarded+1,240,135,&m));
 unsigned colored=0;
 for(int y=2;y<77;y++)for(int x=33;x<110;x++)colored+=guarded[1+y*240+x]==m.view.accent;
 TEST_ASSERT_GREATER_THAN_UINT(200,colored); /* Previously zero: icon hidden by newline. */
 for(int i=0;i<32400;i++)expected[i]=0x0083;
 TEST_ASSERT_TRUE(screen_font_draw_centered(expected,240,135,192,64,SCREEN_FONT_SMALL,hold?"ДЕРЖИТЕ":"КНОПКА:",0x74B3));
 TEST_ASSERT_TRUE(screen_font_draw_centered(expected,240,135,192,79,SCREEN_FONT_SMALL,hold?"КНОПКУ":"СТАРТ / СТОП",0x74B3));
 for(int y=63;y<98;y++)for(int x=147;x<238;x++)TEST_ASSERT_EQUAL_HEX16(expected[y*240+x],guarded[1+y*240+x]);
 if(wake) {
  TEST_ASSERT_TRUE(screen_font_draw_centered(expected,240,135,71,105,SCREEN_FONT_HINT,"СКАЖИТЕ",0x74B3));
  TEST_ASSERT_TRUE(screen_font_draw_centered(expected,240,135,71,120,SCREEN_FONT_HINT,"ЗАТЕЯ",0x74B3));
 }
 for(int y=105;y<135;y++)for(int x=0;x<142;x++)TEST_ASSERT_EQUAL_HEX16(expected[y*240+x],guarded[1+y*240+x]);
}
static void ready_toggle_has_icon_and_explicit_action(void){ready_landscape(false,0);}
static void ready_hold_has_icon_and_explicit_action(void){ready_landscape(true,0);}
static void ready_wake_has_icon_and_invocation(void){ready_landscape(false,1);}
static void selected_idle_overrides_are_preserved(void) {
 const screen_ui_view_t views[]={
  {"ОБНОВЛЯЮ","ПРОШИВКА 73%\nНЕ ВЫКЛЮЧАЙТЕ",0x07e0,SCREEN_ICON_THINKING},
  {"ПРОВЕРЯЮ","ПОСЛЕ ОБНОВЛЕНИЯ",0xF5A8,SCREEN_ICON_THINKING},
  {"ОТЧЁТ","ОТПРАВЛЯЮ\nДИАГНОСТИКУ",0xF5A8,SCREEN_ICON_THINKING},
  {"СЕРВЕР","НЕТ СВЯЗИ",0xF5A8,SCREEN_ICON_THINKING},
  {"СЛУШАЮ","ГОВОРИТЕ",0x07e0,SCREEN_ICON_THINKING},
  {"ГОТОВА","ПОСЛЕ ОБНОВЛЕНИЯ",0x74BF,SCREEN_ICON_IDLE},
 };
 for(unsigned i=0;i<sizeof(views)/sizeof(views[0]);i++) {
  screen_render_model_t m={.view=views[i],.state=STATE_IDLE,.wake_status=1,.device_id="ID 70041ddc4aac"};
  TEST_ASSERT_TRUE(screen_render(guarded+1,240,135,&m));
  m.state=STATE_BOOT; /* Same selected view must not acquire ready-only copy. */
  TEST_ASSERT_TRUE(screen_render(expected,240,135,&m));
  TEST_ASSERT_EQUAL_MEMORY(expected,guarded+1,sizeof(expected));
 }
}
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
int main(void) {UNITY_BEGIN();RUN_TEST(button_left_guidance_is_readable);RUN_TEST(landscape_columns_move_without_reflection);RUN_TEST(rotation_preserves_portrait_and_setup);RUN_TEST(ready_toggle_has_icon_and_explicit_action);RUN_TEST(ready_hold_has_icon_and_explicit_action);RUN_TEST(ready_wake_has_icon_and_invocation);RUN_TEST(selected_idle_overrides_are_preserved);RUN_TEST(bounds_and_layouts);RUN_TEST(long_message_and_setup);RUN_TEST(all_copy);return UNITY_END();}
