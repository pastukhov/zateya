#include "voice_wake_score.h"
#include <string.h>
void voice_wake_score_reset(voice_wake_score_t *s) { memset(s,0,sizeof(*s)); }
bool voice_wake_score_feed(voice_wake_score_t *s, uint8_t p) {
 s->values[s->index++ % 5]=p;
 if(s->warmup<100){s->warmup++;return false;}
 unsigned sum=0;for(unsigned i=0;i<5;i++)sum+=s->values[i];
 return sum>1275/2; /* 0.5 * five uint8 probabilities */
}
