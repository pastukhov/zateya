file(GLOB vad_sources "webrtc/common_audio/vad/*.c" "webrtc/common_audio/signal_processing/*.c")
idf_component_register(SRCS ${vad_sources} INCLUDE_DIRS ".")
target_compile_definitions(${COMPONENT_LIB} PRIVATE WEBRTC_POSIX)
