#include "screen_orientation.h"
#include <math.h>
int screen_orientation_width(screen_rotation_t r) { return r & 1 ? 240 : 135; }
int screen_orientation_height(screen_rotation_t r) { return r & 1 ? 135 : 240; }
int screen_orientation_index(screen_rotation_t r, int x, int y) {
  if(x<0 || x>=135 || y<0 || y>=240) return -1;
  switch(r) {
    case SCREEN_ROTATION_90: return (134-x)*240+y;
    case SCREEN_ROTATION_180: return (239-y)*135+134-x;
    case SCREEN_ROTATION_270: return x*240+239-y;
    default: return y*135+x;
  }
}
bool screen_orientation_sample(screen_orientation_t *s, float x, float y, float z, bool valid, uint32_t now) {
  float ax=fabsf(x), ay=fabsf(y), az=fabsf(z), norm=x*x+y*y+z*z;
  /* g units: reject motion, flat poses and diagonal jitter before settling. */
  if(!valid || !isfinite(norm) || norm<0.65f*0.65f || norm>1.35f*1.35f ||
     (ax>ay?ax:ay)<0.60f || az>0.75f || fabsf(ax-ay)<0.20f) {
    s->pending=false; return false;
  }
  /* Board axes: upright +Y, right edge down +X. Verify on physical StickS3. */
  screen_rotation_t r=ay>ax ? (y>0?SCREEN_ROTATION_0:SCREEN_ROTATION_180) :
                              (x>0?SCREEN_ROTATION_90:SCREEN_ROTATION_270);
  if(r==s->rotation) { s->pending=false; return false; }
  if(!s->pending || r!=s->candidate) { s->candidate=r;s->since=now;s->pending=true;return false; }
  if((uint32_t)(now-s->since)<500) return false;
  s->rotation=r;s->pending=false;return true;
}

bool screen_orientation_sample_sticks3(screen_orientation_t *s,float x,float y,float z,bool valid,uint32_t now) {
 return screen_orientation_sample(s,y,-x,z,valid,now);
}
