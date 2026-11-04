#include <unity.h>
#include <string.h>
#include "voice_settings.h"
#include "voice_config_httpd.h"
#include "../test_main/fakes/hw_fakes.c"
static voice_settings_t settings;
void setUp(void){memset(&settings,0,sizeof(settings));strcpy(settings.wifi[0].ssid,"test-network");strcpy(settings.device_id,"test");strcpy(settings.device_token,"private-token");strcpy(settings.gateway_url,"https://private.test");}
void tearDown(void){}
static bool form(const char *input){char b[512];strcpy(b,input);return voice_config_parse_form(b,&settings);}
static void test_destination_and_secrets(void){
 TEST_ASSERT_FALSE(form("gateway_url=https%3A%2F%2Fevil.test"));setUp();
 TEST_ASSERT_TRUE(form("gateway_url=https%3A%2F%2Fnew.test&device_token=new-token"));
 TEST_ASSERT_FALSE(form("gateway_url=http%3A%2F%2Fplain.test&device_token=new-token"));setUp();
 TEST_ASSERT_TRUE(form("gateway_url=&device_token="));
 char json[512];TEST_ASSERT_TRUE(voice_config_public_status(&settings,json,sizeof(json)));
 TEST_ASSERT_NULL(strstr(json,settings.device_token));TEST_ASSERT_NULL(strstr(json,settings.gateway_url));
 TEST_ASSERT_NULL(strstr(json,"wg_"));TEST_ASSERT_FALSE(voice_config_public_status(&settings,json,8));
}
static void test_wake_settings(void){
 TEST_ASSERT_TRUE(form("wake_enabled=0&wake_pause_seconds=5"));TEST_ASSERT_FALSE(settings.wake_enabled);
 TEST_ASSERT_EQUAL(5000,settings.wake_pause_ms);TEST_ASSERT_FALSE(form("wake_enabled=2"));
 TEST_ASSERT_FALSE(form("wake_pause_seconds=0"));TEST_ASSERT_FALSE(form("wake_pause_seconds=11"));
 voice_settings_factory_defaults(&settings);TEST_ASSERT_TRUE(settings.wake_enabled);TEST_ASSERT_EQUAL(3000,settings.wake_pause_ms);
}
static void test_button_mode_defaults_normalization_and_form(void){
 voice_settings_t defaults;voice_settings_load(&defaults);
 TEST_ASSERT_EQUAL(VOICE_BUTTON_TOGGLE,defaults.button_mode);
 TEST_ASSERT_EQUAL(VOICE_BUTTON_TOGGLE,voice_settings_button_mode_from_stored(0));
 TEST_ASSERT_EQUAL(VOICE_BUTTON_HOLD,voice_settings_button_mode_from_stored(1));
 TEST_ASSERT_EQUAL(VOICE_BUTTON_TOGGLE,voice_settings_button_mode_from_stored(2));
 TEST_ASSERT_EQUAL(VOICE_BUTTON_TOGGLE,voice_settings_button_mode_from_stored(255));
 TEST_ASSERT_TRUE(form("button_mode=hold"));TEST_ASSERT_EQUAL(VOICE_BUTTON_HOLD,settings.button_mode);
 char json[512];TEST_ASSERT_TRUE(voice_config_public_status(&settings,json,sizeof(json)));
 TEST_ASSERT_NOT_NULL(strstr(json,"\"button_mode\":\"hold\""));
 TEST_ASSERT_TRUE(form("wake_enabled=0"));TEST_ASSERT_EQUAL(VOICE_BUTTON_HOLD,settings.button_mode);
 TEST_ASSERT_TRUE(form("button_mode=toggle"));TEST_ASSERT_EQUAL(VOICE_BUTTON_TOGGLE,settings.button_mode);
 const char *bad[]={"button_mode=", "button_mode=HOLD", "button_mode=2", "button_mode=hold+", "button_mode", "button_mode=toggle&button_mode=hold"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++){
  setUp();TEST_ASSERT_FALSE(form(bad[i]));TEST_ASSERT_EQUAL(VOICE_BUTTON_TOGGLE,settings.button_mode);
 }
 voice_settings_factory_defaults(&settings);TEST_ASSERT_EQUAL(VOICE_BUTTON_TOGGLE,settings.button_mode);
}
int main(void){UNITY_BEGIN();RUN_TEST(test_button_mode_defaults_normalization_and_form);RUN_TEST(test_destination_and_secrets);RUN_TEST(test_wake_settings);return UNITY_END();}
