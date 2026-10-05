#include <unity.h>
#include <string.h>

#include "voice_diagnostics.h"
#include "voice_diag_delivery_policy.h"

static void test_events_wrap_and_keep_last_error(void) {
  voice_diag_reset();
  for (uint32_t i = 0; i < 70; ++i)
    voice_diag_event(VOICE_DIAG_UPLOAD_SOCKET_ERROR, i, i + 1, i + 2);
  voice_diag_snapshot_t snapshot;
  voice_diag_snapshot(&snapshot);
  TEST_ASSERT_EQUAL_UINT32(64, snapshot.event_count);
  TEST_ASSERT_EQUAL_UINT32(6, snapshot.events[0].uptime_ms);
  TEST_ASSERT_EQUAL_UINT32(69, snapshot.events[63].uptime_ms);
  TEST_ASSERT_EQUAL(VOICE_DIAG_UPLOAD_SOCKET_ERROR, snapshot.last_error_code);
  voice_diag_snapshot(&snapshot);
  TEST_ASSERT_EQUAL_UINT32(64, snapshot.event_count);
}

static void test_session_counters_do_not_mix(void) {
  voice_diag_reset();
  voice_diag_begin_recording(100);
  voice_diag_record_capture(256, 400);
  voice_diag_record_queue(256, 100);
  voice_diag_record_send(128, 80);
  voice_diag_snapshot_t snapshot;
  voice_diag_snapshot(&snapshot);
  TEST_ASSERT_EQUAL_UINT32(256, snapshot.captured_bytes);
  TEST_ASSERT_EQUAL_UINT32(128, snapshot.sent_bytes);
  TEST_ASSERT_EQUAL_UINT32(400, snapshot.ring_high_water_bytes);
  TEST_ASSERT_EQUAL_UINT32(100, snapshot.upload_high_water_bytes);
  TEST_ASSERT_EQUAL_UINT32(80, snapshot.write_max_ms);
  voice_diag_begin_recording(200);
  voice_diag_snapshot(&snapshot);
  TEST_ASSERT_EQUAL_UINT32(0, snapshot.captured_bytes);
  TEST_ASSERT_EQUAL_UINT32(0, snapshot.sent_bytes);
  TEST_ASSERT_EQUAL_UINT32(2, snapshot.recording_id);
}

static void test_report_is_bounded_and_contains_only_numeric_fields(void) {
  voice_diag_reset();
  voice_diag_event(VOICE_DIAG_REC_RING_OVERFLOW, 500, 32768, 32768);
  voice_diag_snapshot_t snapshot;
  voice_diag_snapshot(&snapshot);
  char small[20];
  TEST_ASSERT_FALSE(voice_diag_snapshot_json(&snapshot, small, sizeof(small)));
  char json[4096];
  TEST_ASSERT_TRUE(voice_diag_snapshot_json(&snapshot, json, sizeof(json)));
  TEST_ASSERT_NOT_NULL(strstr(json, "\"last_error_code\":2"));
  TEST_ASSERT_NOT_NULL(strstr(json, "[500,2,32768,32768]"));
}

static void test_restored_error_does_not_add_an_event(void) {
  voice_diag_reset();
  voice_diag_restore_last_error(VOICE_DIAG_UPLOAD_SOCKET_ERROR);
  voice_diag_snapshot_t snapshot;
  voice_diag_snapshot(&snapshot);
  TEST_ASSERT_EQUAL(VOICE_DIAG_UPLOAD_SOCKET_ERROR, snapshot.last_error_code);
  TEST_ASSERT_EQUAL_UINT32(0, snapshot.event_count);
  voice_diag_restore_last_error(VOICE_DIAG_UPLOAD_COMPLETED);
  voice_diag_snapshot(&snapshot);
  TEST_ASSERT_EQUAL(VOICE_DIAG_UPLOAD_SOCKET_ERROR, snapshot.last_error_code);
}

static void test_delivery_has_three_bounded_attempts_without_network_flap_reset(void) {
  voice_diag_delivery_t delivery = {0};
  TEST_ASSERT_FALSE(voice_diag_delivery_due(&delivery, 100, false, true));
  TEST_ASSERT_TRUE(voice_diag_delivery_due(&delivery, 100, true, true));
  voice_diag_delivery_attempted(&delivery, 100);
  TEST_ASSERT_FALSE(voice_diag_delivery_due(&delivery, 5099, true, true));
  TEST_ASSERT_FALSE(voice_diag_delivery_due(&delivery, 5100, false, true));
  TEST_ASSERT_TRUE(voice_diag_delivery_due(&delivery, 5100, true, true));
  voice_diag_delivery_attempted(&delivery, 5100);
  TEST_ASSERT_FALSE(voice_diag_delivery_due(&delivery, 20099, true, true));
  TEST_ASSERT_TRUE(voice_diag_delivery_due(&delivery, 20100, true, true));
  voice_diag_delivery_attempted(&delivery, 20100);
  TEST_ASSERT_FALSE(voice_diag_delivery_due(&delivery, 999999, true, true));
  voice_diag_delivery_reset(&delivery);
  TEST_ASSERT_TRUE(voice_diag_delivery_due(&delivery, 999999, true, true));
}

static void test_generic_error_does_not_mask_a_specific_current_failure(void) {
  voice_diag_reset();
  voice_diag_restore_last_error(VOICE_DIAG_UPLOAD_SOCKET_ERROR);
  voice_diag_begin_recording(100);
  voice_diag_ensure_error(200);
  TEST_ASSERT_EQUAL(VOICE_DIAG_TURN_FAILED, voice_diag_last_error());
  voice_diag_begin_recording(300);
  voice_diag_event(VOICE_DIAG_REC_RING_OVERFLOW, 400, 32768, 32768);
  voice_diag_ensure_error(401);
  TEST_ASSERT_EQUAL(VOICE_DIAG_REC_RING_OVERFLOW, voice_diag_last_error());
}

int main(void) {
  UNITY_BEGIN();
  RUN_TEST(test_events_wrap_and_keep_last_error);
  RUN_TEST(test_session_counters_do_not_mix);
  RUN_TEST(test_report_is_bounded_and_contains_only_numeric_fields);
  RUN_TEST(test_restored_error_does_not_add_an_event);
  RUN_TEST(test_delivery_has_three_bounded_attempts_without_network_flap_reset);
  RUN_TEST(test_generic_error_does_not_mask_a_specific_current_failure);
  return UNITY_END();
}
