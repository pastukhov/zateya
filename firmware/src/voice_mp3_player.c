#include "voice_mp3_player.h"
#include <math.h>
#include <string.h>

bool voice_mp3_frame_header(const uint8_t *p, size_t n, unsigned *rate,
                            unsigned *channels, unsigned *version, size_t *bytes) {
  if (n < 4 || p[0] != 255 || (p[1] & 224) != 224 || (p[1] & 6) != 2)
    return false;
  unsigned v = (p[1] >> 3) & 3;
  unsigned bitrate = p[2] >> 4;
  unsigned sample_rate = (p[2] >> 2) & 3;
  if (v == 1 || !bitrate || bitrate == 15 || sample_rate == 3 || (p[3] & 3) == 2)
    return false;
  static const unsigned rates[] = {44100, 48000, 32000};
  static const unsigned br1[] = {0,32,40,48,56,64,80,96,112,128,160,192,224,256,320};
  static const unsigned br2[] = {0,8,16,24,32,40,48,56,64,80,96,112,128,144,160};
  *rate = rates[sample_rate] / (v == 3 ? 1 : v == 2 ? 2 : 4);
  *channels = (p[3] >> 6) == 3 ? 1 : 2;
  *version = v;
  if (*rate < 16000) return false;
  *bytes = (v == 3 ? 144000 : 72000) * (v == 3 ? br1[bitrate] : br2[bitrate]) /
           *rate + ((p[2] >> 1) & 1);
  return *bytes >= 4 && *bytes <= VOICE_MP3_MAX_FRAME;
}

static bool drain(voice_mp3_player_t *p) {
  if (p->sent < p->queued) {
    size_t n = p->sink(p->ctx, (const uint8_t *)p->output + p->sent,
                       p->queued - p->sent);
    if (n > p->queued - p->sent || (n & 1)) {
      p->failed = true;
      return false;
    }
    p->sent += n;
  }
  if (p->sent != p->queued) return false;
  p->sent = p->queued = 0;
  return true;
}

static void filter_init(voice_mp3_player_t *p) {
  if (p->rate == 24000) return;
  double sum = 0, cutoff = 10000.0 / p->rate;
  if (cutoff > .45) cutoff = .45;
  for (unsigned i = 0; i < 32; i++) {
    double x = (double)i - 15.5;
    double h = sin(2 * 3.141592653589793 * cutoff * x) / (3.141592653589793 * x);
    h *= .54 - .46 * cos(2 * 3.141592653589793 * i / 31);
    p->taps[i] = (float)h;
    sum += h;
  }
  for (unsigned i = 0; i < 32; i++) p->taps[i] /= (float)sum;
}

static uint32_t be32(const uint8_t *p) {
  return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
         ((uint32_t)p[2] << 8) | p[3];
}

static void inspect_gapless(voice_mp3_player_t *p) {
  /* Xing follows header, optional CRC and MPEG-specific side information. */
  size_t offset = 4 + ((p->input[1] & 1) ? 0 : 2) +
    (p->version == 3 ? (p->channels == 1 ? 17 : 32) : (p->channels == 1 ? 9 : 17));
  if (offset + 8 > p->needed ||
      (memcmp(p->input + offset, "Xing", 4) && memcmp(p->input + offset, "Info", 4)))
    return;
  uint32_t flags = be32(p->input + offset + 4);
  if (flags & ~15U) return;
  offset += 8;
  if (flags & 1) {
    if (offset + 4 > p->needed) return;
    p->declared_frames = be32(p->input + offset);
    offset += 4;
  }
  if (flags & 2) offset += 4;
  if (flags & 4) offset += 100;
  if (flags & 8) offset += 4;
  if (offset + 24 > p->needed || memcmp(p->input + offset, "LAME", 4)) return;
  unsigned delay = ((unsigned)p->input[offset + 21] << 4) | (p->input[offset + 22] >> 4);
  unsigned padding = ((unsigned)(p->input[offset + 22] & 15) << 8) | p->input[offset + 23];
  unsigned samples = p->version == 3 ? 1152 : 576;
  if (!p->declared_frames ||
      (uint64_t)delay + padding >= (uint64_t)p->declared_frames * samples) return;
  p->gapless_metadata = true;
  p->encoder_delay = delay;
  p->encoder_padding = padding;
  /* Never subtract an assumed decoder delay. Espressif's synthesis/first
   * metadata-frame behavior needs a physical PCM capture before enabling trim. */
}

static bool decode(voice_mp3_player_t *p) {
  if (!p->frames) inspect_gapless(p);
  unsigned rate = 0, channels = 0;
  int n = p->ops->decode(p->decoder, p->input, p->needed, p->decoded,
                         VOICE_MP3_PCM_SAMPLES, &rate, &channels);
  if (n < 0 || n > (int)VOICE_MP3_PCM_SAMPLES ||
      (n && (rate != p->rate || channels != p->channels || n % channels)))
    return false;
  size_t count = n / p->channels, out = 0;
  p->pcm_samples += count;
  for (size_t i = 0; i < count; i++) {
    int32_t mixed = p->decoded[i * p->channels];
    if (p->channels == 2) mixed = (mixed + p->decoded[i * 2 + 1]) / 2;
    if (p->rate == 24000) {
      p->output[out++] = (int16_t)mixed;
      continue;
    }
    p->history[p->history_pos] = (float)mixed;
    float value = 0;
    for (unsigned j = 0; j < 32; j++)
      value += p->taps[j] * p->history[(p->history_pos + 32 - j) % 32];
    p->history_pos = (p->history_pos + 1) % 32;
    uint64_t index = p->input_samples++;
    /* next_output is a rational source position with denominator 24000. */
    while (p->next_output <= index * 24000) {
      float sample = value;
      if (index) {
        double fraction = (double)(p->next_output - (index - 1) * 24000) / 24000.0;
        sample = p->previous + (value - p->previous) * (float)fraction;
      }
      if (out >= sizeof(p->output) / sizeof(p->output[0])) return false;
      if (sample > 32767) sample = 32767;
      if (sample < -32768) sample = -32768;
      p->output[out++] = (int16_t)sample;
      p->next_output += p->rate;
    }
    p->previous = value;
  }
  p->queued = out * 2;
  p->sent = 0;
  p->frames++;
  return true;
}

bool voice_mp3_player_init(voice_mp3_player_t *p, const voice_mp3_decoder_t *ops,
                           voice_mp3_sink_t sink, void *ctx) {
  if (!p || !ops || !ops->open || !ops->decode || !ops->close || !sink) return false;
  memset(p, 0, sizeof(*p));
  p->ops = ops;
  p->sink = sink;
  p->ctx = ctx;
  p->needed = 10;
  p->decoder = ops->open();
  return p->decoder != NULL;
}

size_t voice_mp3_player_feed(voice_mp3_player_t *p, const uint8_t *data, size_t length) {
  if (!p || p->failed || p->finished || !p->decoder || (!data && length)) return 0;
  if (!drain(p)) return 0;
  size_t offset = 0;
  while (offset < length) {
    if (p->total >= VOICE_MP3_MAX_BYTES) {
      p->failed = true;
      break;
    }
    if (p->skip) {
      size_t n = length - offset;
      if (n > p->skip) n = p->skip;
      if (n > VOICE_MP3_MAX_BYTES - p->total) n = VOICE_MP3_MAX_BYTES - p->total;
      p->skip -= n;
      p->total += n;
      offset += n;
      continue;
    }
    size_t n = p->needed - p->used;
    if (n > length - offset) n = length - offset;
    if (n > VOICE_MP3_MAX_BYTES - p->total) n = VOICE_MP3_MAX_BYTES - p->total;
    memcpy(p->input + p->used, data + offset, n);
    p->used += n;
    p->total += n;
    offset += n;
    if (p->used < p->needed) continue;
    if (!p->header_checked) {
      p->header_checked = true;
      if (!memcmp(p->input, "ID3", 3)) {
        if (p->input[3] < 3 || p->input[3] > 4 || p->input[4] == 255 ||
            (p->input[5] & (p->input[3] == 3 ? 31 : 15)) ||
            ((p->input[6] | p->input[7] | p->input[8] | p->input[9]) & 128)) {
          p->failed = true;
          break;
        }
        p->skip = ((size_t)p->input[6] << 21) | ((size_t)p->input[7] << 14) |
                  ((size_t)p->input[8] << 7) | p->input[9];
        if (p->input[3] == 4 && (p->input[5] & 16)) p->skip += 10;
        if (p->skip > 65526) {
          p->failed = true;
          break;
        }
        p->used = 0;
        p->needed = 4;
        continue;
      }
      p->needed = 4;
    }
    if (p->needed == 4) {
      unsigned rate, channels, version;
      size_t frame;
      if (!voice_mp3_frame_header(p->input, p->used, &rate, &channels, &version, &frame) ||
          (p->frames && (rate != p->rate || channels != p->channels || version != p->version))) {
        p->failed = true;
        break;
      }
      if (!p->rate) {
        p->rate = rate;
        p->channels = channels;
        p->version = version;
        filter_init(p);
      }
      p->needed = frame;
      if (p->used < p->needed) continue;
    }
    if (!decode(p)) {
      p->failed = true;
      break;
    }
    p->used = 0;
    p->needed = 4;
    if (!drain(p)) break;
  }
  return offset;
}

bool voice_mp3_player_finish(voice_mp3_player_t *p) {
  if (!p || p->failed || !p->decoder) return false;
  if (!drain(p)) return false;
  if (p->skip || p->used || !p->frames || !p->pcm_samples) {
    p->failed = true;
    return false;
  }
  p->finished = true;
  return true;
}

void voice_mp3_player_close(voice_mp3_player_t *p) {
  if (p && p->decoder) {
    p->ops->close(p->decoder);
    p->decoder = NULL;
  }
}
