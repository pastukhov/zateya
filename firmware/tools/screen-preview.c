/* Build/run through render-screen-previews.py; uses the production renderer. */
#include "screen_renderer.h"
#include <stdio.h>
#include <stdlib.h>
static uint16_t pixels[32400];
int main(int argc,char **argv) {
 if(argc!=2)return 2;
 const char *names[]={"recording","error","setup","ota","idle","idle-hold","idle-wake","idle-wake-hold"};
 for(int r=0;r<4;r++) for(int state=0;state<8;state++) {
  screen_render_model_t m={.state=state==0?STATE_RECORDING:state==1?STATE_ERROR:STATE_IDLE,.wifi=true,.usb=true,.battery_percent=83,.backend_status=200,.device_id="ID 70041ddc4aac",.ssid="Zateya-4AAC",.rotation=r};
  m.view=screen_ui_view(m.state);m.timer=screen_ui_recording_timer(0,93000,120);
  if(state==1)m.view.hint="ОШИБКА ПОДКЛЮЧЕНИЯ\nНАЖМИТЕ ДЛЯ СБРОСА";
  if(state==2)m.setup=true;
  if(state==3)m.view=(screen_ui_view_t){"ОБНОВЛЯЮ","ПРОШИВКА 73%\nНЕ ВЫКЛЮЧАЙТЕ",0x07e0,SCREEN_ICON_THINKING};
  m.hold_mode=state==5 || state==7;
  if(state>=6) {m.wake_status=1;m.view.hint="СКАЖИТЕ ЗАТЕЯ\nИЛИ КНОПКА";}
  int w=screen_orientation_width(r),h=screen_orientation_height(r);
  if(!screen_render(pixels,w,h,&m)) {fprintf(stderr,"render did not fit: %s %d\n",names[state],r);return 1;}
  char path[512];snprintf(path,sizeof(path),"%s/%s-%d.ppm",argv[1],names[state],r*90);
  FILE *f=fopen(path,"wb");if(!f)return 2;fprintf(f,"P6\n%d %d\n255\n",w,h);
  for(int i=0;i<w*h;i++){uint16_t c=pixels[i];unsigned char rgb[]={(c>>11)*255/31,((c>>5)&63)*255/63,(c&31)*255/31};fwrite(rgb,1,3,f);}fclose(f);
  snprintf(path,sizeof(path),"%s/%s-%d-physical.ppm",argv[1],names[state],r*90);
  f=fopen(path,"wb");if(!f)return 2;fprintf(f,"P6\n135 240\n255\n");
  for(int y=0;y<240;y++)for(int x=0;x<135;x++) {
   uint16_t c=pixels[screen_orientation_index(r,x,y)];
   unsigned char rgb[]={(c>>11)*255/31,((c>>5)&63)*255/63,(c&31)*255/31};
   fwrite(rgb,1,3,f);
  }
  fclose(f);
 }
 return 0;
}
