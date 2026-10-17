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
int main(void){UNITY_BEGIN();RUN_TEST(test_destination_and_secrets);RUN_TEST(test_wake_settings);return UNITY_END();}
