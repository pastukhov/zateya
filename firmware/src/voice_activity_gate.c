#include "voice_activity_gate.h"
bool voice_activity_claim(atomic_int *activity,voice_activity_t owner){
 if(owner!=VOICE_ACTIVITY_VOICE && owner!=VOICE_ACTIVITY_OTA && owner!=VOICE_ACTIVITY_STORAGE)return false;
 int idle=VOICE_ACTIVITY_IDLE;return atomic_compare_exchange_strong(activity,&idle,owner);
}
bool voice_activity_release(atomic_int *activity,voice_activity_t owner,bool confirmed){
 if((owner!=VOICE_ACTIVITY_VOICE && owner!=VOICE_ACTIVITY_OTA && owner!=VOICE_ACTIVITY_STORAGE) ||
    (owner==VOICE_ACTIVITY_VOICE&&!confirmed))return false;
 int expected=owner;return atomic_compare_exchange_strong(activity,&expected,VOICE_ACTIVITY_IDLE);
}
