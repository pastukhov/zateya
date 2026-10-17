# This file was automatically generated for projects
# without default 'CMakeLists.txt' file.

FILE(GLOB_RECURSE app_sources ${CMAKE_SOURCE_DIR}/src/*.*)

idf_component_register(SRCS ${app_sources} REQUIRES espressif__mdns esp_codec_dev app_update json mbedtls espressif__esp-tflite-micro esphome__esp-micro-speech-features webrtc_vad)
