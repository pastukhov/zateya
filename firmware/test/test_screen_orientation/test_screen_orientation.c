#include <unity.h>
#include "../test_main/fakes/hw_fakes.c"
#include "screen_orientation.h"
#include <limits.h>
void setUp(void) {}
void tearDown(void) {}
static void settle(void) {
  screen_orientation_t s={0};
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,1,0,0,true,100));
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,1,0,0,true,599));
  TEST_ASSERT_TRUE(screen_orientation_sample(&s,1,0,0,true,600));
  TEST_ASSERT_EQUAL(SCREEN_ROTATION_90,s.rotation);
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,0,-1,0,true,700));
  TEST_ASSERT_TRUE(screen_orientation_sample(&s,0,-1,0,true,1200));
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,-1,0,0,true,1300));
  TEST_ASSERT_TRUE(screen_orientation_sample(&s,-1,0,0,true,1800));
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,0,1,0,true,1900));
  TEST_ASSERT_TRUE(screen_orientation_sample(&s,0,1,0,true,2400));
}
static void rejected(void) {
  screen_orientation_t s={0};
  screen_orientation_sample(&s,1,0,0,true,0);
  screen_orientation_sample(&s,.7,.7,0,true,400);
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,1,0,0,true,600));
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,0,0,1,true,1200));
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,0,-3,0,true,1800));
  TEST_ASSERT_FALSE(screen_orientation_sample(&s,0,-1,0,false,2400));
  TEST_ASSERT_EQUAL(0,s.rotation);
}
static void wrap(void) {
 screen_orientation_t s={0};
 screen_orientation_sample(&s,-1,0,0,true,UINT_MAX-200);
 TEST_ASSERT_TRUE(screen_orientation_sample(&s,-1,0,0,true,300));
}
static void mounting(void) {
 screen_orientation_t s={0};
 screen_orientation_sample_sticks3(&s,0,1,0,true,0);
 TEST_ASSERT_TRUE(screen_orientation_sample_sticks3(&s,0,1,0,true,500));
 TEST_ASSERT_EQUAL(SCREEN_ROTATION_90,s.rotation);
 screen_orientation_sample_sticks3(&s,-1,0,0,true,600);
 TEST_ASSERT_TRUE(screen_orientation_sample_sticks3(&s,-1,0,0,true,1100));
 TEST_ASSERT_EQUAL(SCREEN_ROTATION_0,s.rotation);
}
static void geometry(void) {
 for(int r=0;r<4;r++) {
  unsigned char seen[32400]={0};
  for(int y=0;y<240;y++) for(int x=0;x<135;x++) {
   int n=screen_orientation_index(r,x,y);
   TEST_ASSERT_TRUE(n>=0 && n<32400); TEST_ASSERT_FALSE(seen[n]);seen[n]=1;
  }
 }
 /* Semantic corners: TL,TR,BL,BR source coordinates for each physical panel. */
 const int expected[4][4]={{0,134,32265,32399},{32160,0,32399,239},{32399,32265,134,0},{239,32399,0,32160}};
 for(int r=0;r<4;r++) {
  TEST_ASSERT_EQUAL(expected[r][0],screen_orientation_index(r,0,0));
  TEST_ASSERT_EQUAL(expected[r][1],screen_orientation_index(r,134,0));
  TEST_ASSERT_EQUAL(expected[r][2],screen_orientation_index(r,0,239));
  TEST_ASSERT_EQUAL(expected[r][3],screen_orientation_index(r,134,239));
 }
 TEST_ASSERT_EQUAL(0,screen_orientation_index(0,0,0));
 TEST_ASSERT_EQUAL(32160,screen_orientation_index(1,0,0));
 TEST_ASSERT_EQUAL(32399,screen_orientation_index(2,0,0));
 TEST_ASSERT_EQUAL(239,screen_orientation_index(3,0,0));
}
static void native_button_edge_becomes_landscape_side(void) {
 /* Front button is beyond native portrait y=239. The whole adjacent edge
  * must become logical right at 90 and logical left at 270, regardless of IMU. */
 for(int x=0;x<135;x++) {
  TEST_ASSERT_EQUAL(239,screen_orientation_index(SCREEN_ROTATION_90,x,239)%240);
  TEST_ASSERT_EQUAL(0,screen_orientation_index(SCREEN_ROTATION_270,x,239)%240);
 }
}
int main(void) { UNITY_BEGIN();RUN_TEST(settle);RUN_TEST(rejected);RUN_TEST(wrap);RUN_TEST(geometry);RUN_TEST(mounting);RUN_TEST(native_button_edge_becomes_landscape_side);return UNITY_END(); }
