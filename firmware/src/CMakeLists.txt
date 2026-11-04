# This file was automatically generated for projects
# without default 'CMakeLists.txt' file.

execute_process(COMMAND python3 ${CMAKE_SOURCE_DIR}/../deploy/firmware/prepare-static-cues.py
  --assets ${CMAKE_SOURCE_DIR}/assets --header ${CMAKE_SOURCE_DIR}/include/voice_static_cues_manifest.h
  RESULT_VARIABLE cue_validation)
if(NOT cue_validation EQUAL 0)
  message(FATAL_ERROR "Static voice cue validation failed")
endif()

FILE(GLOB_RECURSE app_sources ${CMAKE_SOURCE_DIR}/src/*.*)

idf_component_register(SRCS ${app_sources} EMBED_FILES "../assets/voice-listening.pcm" "../assets/voice-processing.pcm" "../assets/voice-offline.pcm" REQUIRES espressif__mdns esp_codec_dev app_update json mbedtls espressif__esp-tflite-micro esphome__esp-micro-speech-features webrtc_vad)
